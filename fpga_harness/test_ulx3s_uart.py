"""Tests for the ULX3S UART driver's response checking.

The negative cases carry the weight here. A driver that prints a board's reply
and exits zero looks identical to a working one in CI logs, so these tests feed
the driver a complete, well-formed, *wrong* 16-byte MUL response and require a
non-zero exit. No serial port and no board are involved.
"""

from __future__ import annotations

import re
import shlex
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import ulx3s_uart
from ulx3s_uart import expected_mul

_STREAM_ALU = (
    Path(__file__).resolve().parent.parent
    / "asic_core"
    / "rtl"
    / "leanvm_b_stream_alu.sv"
)

# Same vector the RTL testbench uses, so the host tool and the simulation are
# checked against one shared expectation.
MUL_A = bytes.fromhex("112233445566778899aabbccddeeff01")
MUL_B = bytes.fromhex("02000000000000000000000000000000")
MUL_EXPECTED = bytes.fromhex("22446688aaccee1033557799bbddff03")


class FakeSerial:
    """Minimal stand-in that replays a canned reply once a command is complete."""

    def __init__(self, response: bytes, command_len: int) -> None:
        self._response = response
        self._command_len = command_len
        self._written = bytearray()
        self._pending = bytearray()
        self.closed = False

    @property
    def in_waiting(self) -> int:
        return len(self._pending)

    def write(self, data: bytes) -> int:
        self._written.extend(data)
        if len(self._written) == self._command_len:
            self._pending.extend(self._response)
        return len(data)

    def flush(self) -> None:
        pass

    def read(self, n: int = 1) -> bytes:
        chunk = bytes(self._pending[:n])
        del self._pending[:n]
        return chunk

    def reset_input_buffer(self) -> None:
        self._pending.clear()

    def reset_output_buffer(self) -> None:
        self._written.clear()

    def close(self) -> None:
        self.closed = True

    @property
    def written(self) -> bytes:
        return bytes(self._written)


class IdleSerial:
    """An idle port whose configured blocking read must never be called."""

    in_waiting = 0

    def read(self, _n: int = 1) -> bytes:
        raise AssertionError("drain attempted a blocking read on an idle port")


def run_status(response: bytes) -> int:
    """Run the driver's status path against a canned reply."""
    fake = FakeSerial(response, command_len=2)  # ABORT then STATUS
    with mock.patch.object(ulx3s_uart, "open_port", return_value=fake):
        return ulx3s_uart.main(["--port", "/dev/null", "--tx", "status"])


def run_mul(response: bytes) -> int:
    """Run the driver's mul path against a canned 16-byte reply."""
    fake = FakeSerial(response, command_len=1 + 1 + 32)
    with mock.patch.object(ulx3s_uart, "open_port", return_value=fake):
        return ulx3s_uart.main(
            ["--port", "/dev/null", "--tx", "mul", "--payload", (MUL_A + MUL_B).hex()]
        )


class ExpectedMulTest(unittest.TestCase):
    def test_matches_independent_vector(self):
        self.assertEqual(expected_mul(MUL_A, MUL_B), MUL_EXPECTED)

    def test_multiplication_by_one_is_identity(self):
        one = bytes([1]) + bytes(15)
        self.assertEqual(expected_mul(MUL_A, one), MUL_A)

    def test_is_commutative(self):
        self.assertEqual(expected_mul(MUL_A, MUL_B), expected_mul(MUL_B, MUL_A))

    def test_rejects_wrong_operand_length(self):
        with self.assertRaises(ValueError):
            expected_mul(MUL_A[:15], MUL_B)


class DrainTest(unittest.TestCase):
    def test_idle_port_is_polled_without_a_blocking_read(self):
        with mock.patch.object(ulx3s_uart.time, "sleep"), mock.patch.object(
            ulx3s_uart.time, "time", side_effect=[0.0, 0.01, 0.06]
        ):
            self.assertEqual(ulx3s_uart.drain(IdleSerial()), b"")

    def test_available_byte_read_is_bounded_by_settle_deadline(self):
        class StaleCountSerial:
            timeout = 2.0
            in_waiting = 1

            def read(self, _n: int = 1) -> bytes:
                self.observed_timeout = self.timeout
                return b""

        fake = StaleCountSerial()
        with mock.patch.object(
            ulx3s_uart.time, "time", side_effect=[10.0, 10.0, 10.051]
        ):
            self.assertEqual(ulx3s_uart.drain(fake, settle=0.05), b"")
        self.assertGreater(fake.observed_timeout, 0)
        self.assertAlmostEqual(fake.observed_timeout, 0.05)
        self.assertEqual(fake.timeout, 2.0)

    def test_blocking_in_waiting_cannot_outlast_drain_deadline(self):
        """Mutation-sensitive: direct ``ser.in_waiting`` would wait 30 seconds."""
        release = threading.Event()
        self.addCleanup(release.set)

        class StalledQuery:
            @property
            def in_waiting(self) -> int:
                release.wait(30)
                return 0

        start = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, "in_waiting"):
            ulx3s_uart.drain(StalledQuery(), settle=0.05)
        self.assertLess(time.monotonic() - start, 1.0)


class MulExitStatusTest(unittest.TestCase):
    def test_correct_product_succeeds(self):
        self.assertEqual(run_mul(MUL_EXPECTED), 0)

    def test_single_flipped_bit_is_rejected(self):
        wrong = bytearray(MUL_EXPECTED)
        wrong[0] ^= 0x01
        self.assertEqual(len(wrong), 16)
        self.assertEqual(run_mul(bytes(wrong)), 1)

    def test_flipped_bit_in_last_byte_is_rejected(self):
        wrong = bytearray(MUL_EXPECTED)
        wrong[15] ^= 0x80
        self.assertEqual(run_mul(bytes(wrong)), 1)

    def test_all_zero_response_is_rejected(self):
        self.assertEqual(run_mul(bytes(16)), 1)

    def test_operands_echoed_back_are_rejected(self):
        # A bridge that loops input to output returns a plausible 16 bytes.
        self.assertEqual(run_mul(MUL_A), 1)

    def test_driver_sends_the_documented_command_framing(self):
        fake = FakeSerial(MUL_EXPECTED, command_len=1 + 1 + 32)
        with mock.patch.object(ulx3s_uart, "open_port", return_value=fake):
            ulx3s_uart.main(
                ["--port", "/dev/null", "--tx", "mul", "--payload", (MUL_A + MUL_B).hex()]
            )
        self.assertEqual(
            fake.written,
            bytes([ulx3s_uart.ABORT, ulx3s_uart.MUL128]) + MUL_A + MUL_B,
        )

    def test_cli_timeout_reaches_the_response_deadline(self):
        fake = FakeSerial(MUL_EXPECTED, command_len=1 + 1 + 32)
        with mock.patch.object(ulx3s_uart, "open_port", return_value=fake), mock.patch.object(
            ulx3s_uart, "recv_response", return_value=MUL_EXPECTED
        ) as recv:
            rc = ulx3s_uart.main(
                [
                    "--port",
                    "/dev/null",
                    "--tx",
                    "mul",
                    "--timeout",
                    "0.125",
                    "--payload",
                    (MUL_A + MUL_B).hex(),
                ]
            )
        self.assertEqual(rc, 0)
        recv.assert_called_once_with(fake, 16, timeout=0.125)


class StatusSignatureTest(unittest.TestCase):
    """`--tx status` is the default command, so an unchecked reply is the widest hole."""

    def test_signature_matches_the_rtl_status_bytes(self):
        # Parse status_byte()'s case arms so the host constant cannot drift from RTL.
        body = _STREAM_ALU.read_text().split("function automatic [7:0] status_byte;")[1]
        body = body.split("endfunction")[0]
        arms = dict(
            (int(i), int(v, 16))
            for i, v in re.findall(r"4'd(\d):\s*status_byte\s*=\s*8'h([0-9a-fA-F]{2});", body)
        )
        rtl = bytes(arms[i] for i in range(4))
        self.assertEqual(rtl, ulx3s_uart.STATUS_SIGNATURE)

    def test_documented_signature_succeeds(self):
        self.assertEqual(run_status(ulx3s_uart.STATUS_SIGNATURE), 0)

    def test_four_garbage_bytes_are_rejected(self):
        self.assertEqual(run_status(bytes.fromhex("deadbeef")), 1)

    def test_all_zero_response_is_rejected(self):
        self.assertEqual(run_status(bytes(4)), 1)

    def test_idle_line_pulled_high_is_rejected(self):
        self.assertEqual(run_status(b"\xff" * 4), 1)

    def test_single_flipped_bit_is_rejected(self):
        wrong = bytearray(ulx3s_uart.STATUS_SIGNATURE)
        wrong[2] ^= 0x01
        self.assertEqual(run_status(bytes(wrong)), 1)

    def test_byte_swapped_signature_is_rejected(self):
        self.assertEqual(run_status(ulx3s_uart.STATUS_SIGNATURE[::-1]), 1)

    def test_error_response_is_rejected(self):
        # S_ERROR_TX emits 0xe0 for an unknown opcode; a bridge that mis-decodes
        # STATUS must not look healthy.
        self.assertEqual(run_status(b"\xe0" * 4), 1)

    def test_driver_sends_the_documented_command_framing(self):
        fake = FakeSerial(ulx3s_uart.STATUS_SIGNATURE, command_len=2)
        with mock.patch.object(ulx3s_uart, "open_port", return_value=fake):
            ulx3s_uart.main(["--port", "/dev/null", "--tx", "status"])
        self.assertEqual(fake.written, bytes([ulx3s_uart.ABORT, ulx3s_uart.STATUS]))

    def test_short_reply_is_not_silently_accepted(self):
        with mock.patch("sys.stderr") as stderr:
            self.assertEqual(run_status(ulx3s_uart.STATUS_SIGNATURE[:3]), 2)
        self.assertIn("expected 4 bytes, got 3", str(stderr.write.call_args_list))

    def test_serial_transport_failure_is_reported_as_communication_error(self):
        if ulx3s_uart.serial is None:
            self.skipTest("pyserial is not installed")
        fake = FakeSerial(b"", command_len=2)
        with mock.patch.object(
            ulx3s_uart, "open_port", return_value=fake
        ), mock.patch.object(
            ulx3s_uart,
            "tx_status",
            side_effect=ulx3s_uart.serial.SerialTimeoutException("write timed out"),
        ), mock.patch("sys.stderr") as stderr:
            rc = ulx3s_uart.main(["--port", "/dev/null", "--tx", "status"])
        self.assertEqual(rc, 2)
        self.assertIn("write timed out", str(stderr.write.call_args_list))
        self.assertTrue(fake.closed)


class _FakeClock:
    """Virtual clock, so deadline behaviour is asserted without real waiting."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _StallingPort:
    """Delivers one byte late, then stalls for whatever timeout it was armed with."""

    def __init__(self, clock, first_byte_after: float, port_timeout: float) -> None:
        self.timeout = port_timeout
        self._clock = clock
        self._first_byte_after = first_byte_after
        self.armed: list = []
        self.calls = 0

    def read(self, n: int) -> bytes:
        self.calls += 1
        self.armed.append(self.timeout)
        if self.calls == 1:
            self._clock.advance(self._first_byte_after)
            return b"\x01"
        # A real blocking read consumes exactly the timeout it was armed with.
        self._clock.advance(self.timeout)
        return b""


class RecvExactDeadlineTest(unittest.TestCase):
    """`recv_exact` must bound the whole call, not each read separately.

    pyserial applies the timeout set in open_port to every individual read, so
    a byte arriving just before the deadline used to buy the read after it a
    whole fresh timeout: a 2 s budget took 3.9 s. Re-arm from the time left.
    """

    def _run(self, budget=2.0, first_byte_after=1.9):
        clock = _FakeClock()
        port = _StallingPort(clock, first_byte_after, port_timeout=budget)
        start = clock.t
        with mock.patch.object(ulx3s_uart.time, "time", clock), mock.patch.object(
            ulx3s_uart.time, "sleep", lambda s: None
        ):
            with self.assertRaises(TimeoutError):
                ulx3s_uart.recv_exact(port, 4, timeout=budget)
        return port, clock.t - start

    def test_call_does_not_outlive_its_budget(self):
        _, elapsed = self._run(budget=2.0, first_byte_after=1.9)
        self.assertLessEqual(elapsed, 2.0 + 1e-9, "a late byte bought a second full timeout")

    def test_each_read_is_armed_with_only_the_time_left(self):
        port, _ = self._run(budget=2.0, first_byte_after=1.9)
        self.assertGreaterEqual(port.calls, 2)
        self.assertAlmostEqual(port.armed[1], 0.1, places=9)

    def test_armed_timeouts_never_increase(self):
        port, _ = self._run(budget=2.0, first_byte_after=0.5)
        self.assertEqual(port.armed, sorted(port.armed, reverse=True))

    def test_port_timeout_is_restored_for_the_next_transaction(self):
        port, _ = self._run(budget=2.0, first_byte_after=1.9)
        self.assertEqual(port.timeout, 2.0)

    def test_a_port_without_a_timeout_attribute_still_works(self):
        # Re-arming must not require the object to already expose .timeout.
        class Bare:
            def __init__(self, data):
                self.data = bytearray(data)

            def read(self, n):
                chunk = bytes(self.data[:n])
                del self.data[:n]
                return chunk

        self.assertEqual(
            ulx3s_uart.recv_exact(Bare(ulx3s_uart.STATUS_SIGNATURE), 4, timeout=1.0),
            ulx3s_uart.STATUS_SIGNATURE,
        )


class AbortByteInPayloadTest(unittest.TestCase):
    """0x7f inside an operand aborts the transaction in the bridge.

    uart_bridge.sv derives its abort pulse from any received 0x7f, so an
    operand containing that byte is torn down mid-flight and the core replies
    0xe0. Confirmed in simulation: a SET128 whose payload byte 5 is 0x7f comes
    back as 15 bytes with 0xe0 from byte 5 onward. Until the bridge framing
    distinguishes payload from command, the host must refuse such an operand
    rather than print MATCH: False and let a reader blame the silicon.
    """

    def test_set_payload_carrying_the_abort_byte_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            ulx3s_uart.tx_set(object(), bytes([0x7F]) + bytes(15))
        self.assertIn("7f", str(ctx.exception))

    def test_offsets_of_every_abort_byte_are_reported(self):
        payload = bytearray(16)
        payload[3] = ulx3s_uart.ABORT
        payload[11] = ulx3s_uart.ABORT
        with self.assertRaises(ValueError) as ctx:
            ulx3s_uart.reject_abort_byte("operand", bytes(payload))
        self.assertIn("3", str(ctx.exception))
        self.assertIn("11", str(ctx.exception))

    def test_either_mul_operand_is_checked(self):
        clean, dirty = bytes(16), bytes([ulx3s_uart.ABORT]) + bytes(15)
        for a, b in ((dirty, clean), (clean, dirty)):
            with self.subTest(a=a[:1], b=b[:1]):
                with self.assertRaises(ValueError):
                    ulx3s_uart.tx_mul(object(), a, b)

    def test_either_xor_operand_is_checked(self):
        clean, dirty = bytes(16), bytes(15) + bytes([ulx3s_uart.ABORT])
        for a, b in ((dirty, clean), (clean, dirty)):
            with self.subTest(a=a[-1:], b=b[-1:]):
                with self.assertRaises(ValueError):
                    ulx3s_uart.tx_xor(object(), a, b)

    def test_operands_without_the_abort_byte_are_untouched(self):
        # The guard must not fire on the vectors the bench and CI already use.
        ulx3s_uart.reject_abort_byte("a", MUL_A)
        ulx3s_uart.reject_abort_byte("b", MUL_B)
        ulx3s_uart.reject_abort_byte("expected", MUL_EXPECTED)

    def test_cli_exits_two_not_one_for_an_uncarryable_payload(self):
        # Exit 1 means "the board answered wrong". This is not that, and a CI
        # log that conflates them sends someone hunting a hardware fault.
        payload = (bytes([ulx3s_uart.ABORT]) + bytes(15) + bytes(16)).hex()
        fake = FakeSerial(b"", command_len=99)
        with mock.patch.object(ulx3s_uart, "open_port", return_value=fake):
            rc = ulx3s_uart.main(["--port", "/dev/null", "--tx", "mul", "--payload", payload])
        self.assertEqual(rc, 2)
        self.assertEqual(fake.written, b"", "no bytes may reach the link")


class SurplusResponseByteTest(unittest.TestCase):
    """A reply that merely *starts* correctly is not a correct reply.

    `recv_exact` returns the instant the nth byte lands, so a duplicated or
    spurious trailing byte used to stay queued while the driver compared only
    the prefix and exited 0 -- a bridge stuttering an extra byte read as a
    clean pass. The link must be settled and found silent before a match is
    reported.
    """

    def test_status_prefix_followed_by_a_surplus_byte_is_rejected(self):
        self.assertNotEqual(run_status(ulx3s_uart.STATUS_SIGNATURE + b"\x00"), 0)

    def test_duplicated_status_reply_is_rejected(self):
        self.assertNotEqual(run_status(ulx3s_uart.STATUS_SIGNATURE * 2), 0)

    def test_surplus_is_a_transport_fault_not_a_wrong_answer(self):
        # Exit 1 means "the board answered wrong". A stuttering link is not
        # that, and conflating them sends someone hunting a datapath bug.
        with mock.patch("sys.stderr") as stderr:
            self.assertEqual(run_status(ulx3s_uart.STATUS_SIGNATURE + b"\x00"), 2)
        self.assertIn("surplus", str(stderr.write.call_args_list))

    def test_mul_result_followed_by_an_error_byte_is_rejected(self):
        self.assertNotEqual(run_mul(MUL_EXPECTED + b"\xe0"), 0)

    def test_mul_result_followed_by_a_surplus_byte_exits_two(self):
        self.assertEqual(run_mul(MUL_EXPECTED + b"\x00"), 2)

    def test_exact_length_replies_still_pass(self):
        # The guard must not fire on the clean case it is wrapped around.
        self.assertEqual(run_status(ulx3s_uart.STATUS_SIGNATURE), 0)
        self.assertEqual(run_mul(MUL_EXPECTED), 0)

    def test_surplus_bytes_are_named_in_the_message(self):
        fake = FakeSerial(b"", command_len=0)
        fake._pending.extend(ulx3s_uart.STATUS_SIGNATURE + b"\xab\xcd")
        with self.assertRaises(ValueError) as ctx:
            ulx3s_uart.recv_response(fake, 4)
        self.assertIn("abcd", str(ctx.exception))

    def test_every_command_path_uses_the_settling_reader(self):
        # A new command that reaches for recv_exact directly would silently
        # reopen the hole, so pin the seam rather than the four call sites.
        source = Path(ulx3s_uart.__file__).read_text()
        body = source.split("# MinCore constants for independent oracle")[1]
        self.assertNotIn("recv_exact(", body, "a command bypasses recv_response")
        self.assertIn("recv_response(", body)


class RecvResponseTest(unittest.TestCase):
    def test_returns_the_response_when_the_link_is_silent(self):
        fake = FakeSerial(b"", command_len=0)
        fake._pending.extend(ulx3s_uart.STATUS_SIGNATURE)
        self.assertEqual(
            ulx3s_uart.recv_response(fake, 4), ulx3s_uart.STATUS_SIGNATURE
        )

    def test_raises_when_anything_follows_the_response(self):
        fake = FakeSerial(b"", command_len=0)
        fake._pending.extend(ulx3s_uart.STATUS_SIGNATURE + b"\x99")
        with self.assertRaises(ValueError):
            ulx3s_uart.recv_response(fake, 4)

    def test_settle_window_outlasts_a_byte_at_the_configured_baud(self):
        # 10 bit times at BAUD is how long a straggler needs to land; a settle
        # window shorter than that would race the byte it exists to catch.
        self.assertGreater(ulx3s_uart.SETTLE_S, 10.0 / ulx3s_uart.BAUD)


_DOC = (
    Path(__file__).resolve().parent.parent / "docs" / "ULX3S_SMOKE_AND_UART.md"
)
_INVOCATION = "python3 -m fpga_harness.ulx3s_uart"


def _documented_invocations():
    """Every advertised command line, as (source, argv-after-the-module-name)."""
    sources = [("ulx3s_uart docstring", ulx3s_uart.__doc__), (_DOC.name, _DOC.read_text())]
    for origin, text in sources:
        for raw in text.splitlines():
            line = raw.strip().lstrip("$ ").strip()
            if not line.startswith(_INVOCATION):
                continue
            yield origin, line, shlex.split(line)[3:]


class DocumentedUsageTest(unittest.TestCase):
    """A copy-pasteable example that argparse rejects is a broken example.

    The shipped usage line said `--tx 03` -- the opcode byte rather than the
    command name -- so the one command a new user runs first exited 2 before
    ever opening the port.
    """

    def test_examples_are_actually_found(self):
        # Guards the parser below from passing vacuously if the docs are reshaped.
        found = list(_documented_invocations())
        self.assertGreaterEqual(len(found), 3, f"only found: {found}")

    def test_every_documented_command_line_parses(self):
        parser = ulx3s_uart.build_parser()
        for origin, line, argv in _documented_invocations():
            with self.subTest(source=origin, line=line):
                # parse_args calls sys.exit on a bad option instead of raising.
                try:
                    parser.parse_args(argv)
                except SystemExit as exc:
                    self.fail(f"{origin} advertises a command argparse rejects: {line} ({exc})")

    def test_every_documented_payload_has_the_right_width(self):
        parser = ulx3s_uart.build_parser()
        for origin, line, argv in _documented_invocations():
            with self.subTest(source=origin, line=line):
                args = parser.parse_args(argv)
                want = ulx3s_uart.PAYLOAD_BYTES[args.tx]
                payload = bytes.fromhex(args.payload) if args.payload else b""
                self.assertEqual(
                    len(payload), want, f"{origin}: {args.tx} needs {want} payload bytes"
                )

    def test_opcode_byte_is_not_accepted_as_a_command_name(self):
        # The exact regression: `--tx 03` must stay rejected, and must not be
        # silently coerced into SET128 either.
        for opcode in ("03", "0x03", str(ulx3s_uart.SET128)):
            with self.subTest(opcode=opcode):
                with self.assertRaises(SystemExit):
                    ulx3s_uart.build_parser().parse_args(
                        ["--port", "/dev/null", "--tx", opcode]
                    )

    def test_parser_choices_cover_every_payload_width_entry(self):
        parser = ulx3s_uart.build_parser()
        choices = next(a.choices for a in parser._actions if a.dest == "tx")
        self.assertEqual(set(choices), set(ulx3s_uart.PAYLOAD_BYTES))


if __name__ == "__main__":
    unittest.main()

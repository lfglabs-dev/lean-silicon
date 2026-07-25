import io
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from fpga_harness.host import mincore_uart
from fpga_harness.host.mincore_uart import (AbortUnavailable, MinCoreDriver,
    MinCoreError, ResponseError, STATUS_BYTES, TransportFailure, TransportTimeout,
    VECTORS, decode_response, encode_request, main, record_evidence, repo_provenance)


class Clock:
    def __init__(self): self.value = 0.0
    def __call__(self): self.value += 0.01; return self.value


class FakeSerial:
    def __init__(self, incoming=b"", read_limit=99, write_limit=99, responses=()):
        self.incoming, self.written = bytearray(incoming), bytearray()
        self.read_limit, self.write_limit = read_limit, write_limit
        self.responses = list(responses)
    @property
    def in_waiting(self): return len(self.incoming)
    def read(self, size=1):
        take = min(size, self.read_limit, len(self.incoming))
        out, self.incoming = bytes(self.incoming[:take]), self.incoming[take:]
        return out
    def write(self, data):
        take = min(len(data), self.write_limit)
        self.written.extend(data[:take])
        if self.responses:
            self.incoming.extend(self.responses.pop(0))
        return take


def independent_polynomial_product(a_bytes, b_bytes):
    """Long reduction, intentionally separate from the host transport."""
    a, b = int.from_bytes(a_bytes, "little"), int.from_bytes(b_bytes, "little")
    product = 0
    for bit in range(128):
        if (b >> bit) & 1:
            product ^= a << bit
    modulus = (1 << 128) | 0x87
    for degree in range(254, 127, -1):
        if (product >> degree) & 1:
            product ^= modulus << (degree - 128)
    return (product & ((1 << 128) - 1)).to_bytes(16, "little")


class MinCoreUartTests(unittest.TestCase):
    def test_hardcoded_golden_vectors_and_little_endian_requests(self):
        self.assertEqual(encode_request("set", value=VECTORS["set128"].value).hex(), "03000102030405060708090a0b0c0d0e0f")
        self.assertEqual(encode_request("xor", a=VECTORS["xor128"].a, b=VECTORS["xor128"].b).hex(), "0100f001f102f203f304f405f506f607f708f809f90afa0bfb0cfc0dfd0efe0fff")
        self.assertEqual(encode_request("mul", a=VECTORS["mul128"].a, b=VECTORS["mul128"].b).hex(), "0200112233445566778899aabbccddeeffffeeddccbbaa99887766554433221100")
        self.assertEqual(VECTORS["mul128"].expected.hex(), "c043248e79cfa802850661cb3c8aed47")
        self.assertEqual(independent_polynomial_product(VECTORS["mul128"].a, VECTORS["mul128"].b), VECTORS["mul128"].expected)

    def test_partial_reads_writes_and_stale_drain(self):
        v = VECTORS["set128"]
        serial = FakeSerial(b"stale", read_limit=3, write_limit=4, responses=(v.expected,))
        request, response = MinCoreDriver(serial, .2, Clock()).exchange("set", value=v.value)
        self.assertEqual(request, encode_request("set", value=v.value)); self.assertEqual(response, v.expected)
        self.assertEqual(bytes(serial.written), request)

    def test_timeout_reports_exact_progress_without_retry(self):
        serial = FakeSerial()
        with self.assertRaisesRegex(TransportTimeout, r"0/16 response bytes"):
            MinCoreDriver(serial, .03, Clock()).exchange("set", value=VECTORS["set128"].value)
        self.assertEqual(bytes(serial.written), encode_request("set", value=VECTORS["set128"].value))

    def test_deadlines_apply_even_while_io_makes_progress(self):
        serial = FakeSerial(write_limit=1)
        with self.assertRaisesRegex(TransportTimeout, r"write timeout after 3/17 request bytes"):
            MinCoreDriver(serial, .025, Clock()).exchange("set", value=VECTORS["set128"].value)

        serial = FakeSerial(read_limit=1, responses=(STATUS_BYTES,))
        with self.assertRaisesRegex(TransportTimeout, r"read timeout after 3/4 response bytes"):
            MinCoreDriver(serial, .025, Clock()).exchange("status")

    def test_stale_drain_is_bounded_and_invalid_write_counts_fail(self):
        class NoisySerial(FakeSerial):
            @property
            def in_waiting(self): return 1
            def read(self, size=1): return b"x"
        with self.assertRaisesRegex(TransportTimeout, "stale-input drain timeout"):
            MinCoreDriver(NoisySerial(), .03, Clock()).exchange("status")

        class BadWriteCount(FakeSerial):
            def write(self, data): return len(data) + 1
        with self.assertRaisesRegex(TransportFailure, "invalid write count"):
            MinCoreDriver(BadWriteCount(), .2, Clock()).exchange("status")

    def test_extra_bytes_and_bad_status_are_rejected(self):
        serial = FakeSerial(responses=(STATUS_BYTES + b"\x00",))
        with self.assertRaisesRegex(ResponseError, "unexpected buffered"):
            MinCoreDriver(serial, .2, Clock()).exchange("status")
        with self.assertRaisesRegex(ResponseError, "STATUS response"):
            decode_response("status", b"\x01\x01\x00\x08")

    def test_framing_loss_and_abort_are_explicit(self):
        serial = FakeSerial(responses=(b"\xe0",))
        driver = MinCoreDriver(serial, .03, Clock())
        with self.assertRaisesRegex(TransportTimeout, r"1/16 response bytes"):
            driver.exchange("set", value=VECTORS["set128"].value)
        with self.assertRaisesRegex(TransportFailure, "unusable after an indeterminate exchange"):
            driver.exchange("status")
        with self.assertRaises(AbortUnavailable):
            MinCoreDriver(FakeSerial(), .2, Clock()).abort()

    def test_buffered_input_query_failure_is_a_handled_transport_failure(self):
        class DisconnectingSerial(FakeSerial):
            @property
            def in_waiting(self): raise OSError("device disconnected")
        with self.assertRaisesRegex(TransportFailure, "buffered-input query failed"):
            MinCoreDriver(DisconnectingSerial(), .2, Clock()).exchange("status")
        self.assertTrue(issubclass(TransportFailure, MinCoreError))

    def test_no_response_transaction_is_flushed_before_the_port_can_close(self):
        events = []
        class FlushingSerial(FakeSerial):
            def write(self, data): events.append("write"); return super().write(data)
            def flush(self): events.append("flush")
        request, response = MinCoreDriver(FlushingSerial(), .2, Clock()).exchange("clear")
        self.assertEqual(request, b"\x7d")
        self.assertEqual(response, b"")
        self.assertEqual(events, ["write", "flush"])

        class BrokenFlush(FakeSerial):
            def flush(self): raise OSError("link lost")
        with self.assertRaisesRegex(TransportFailure, "output flush failed"):
            MinCoreDriver(BrokenFlush(), .2, Clock()).exchange("clear")

    def test_a_stalled_flush_cannot_outlast_the_configured_timeout(self):
        release = threading.Event()
        self.addCleanup(release.set)
        class StalledFlush(FakeSerial):
            def flush(self): release.wait(30)
        start = time.monotonic()
        with self.assertRaisesRegex(TransportTimeout, "flush timeout"):
            MinCoreDriver(StalledFlush(), .1, Clock()).exchange("clear")
        self.assertLess(time.monotonic() - start, 5)

    def test_evidence_distinguishes_a_dirty_source_tree(self):
        head = "0" * 40
        for dirty in (False, True, None):
            output = io.BytesIO()
            record_evidence(output, provenance=(head, dirty), operation="clear",
                            request=b"\x7d", response=b"", expected=None, passed=None,
                            execution_attempted=True, serial_response_observed=False)
            evidence = json.loads(output.getvalue())
            self.assertEqual(evidence["repo_head"], head)
            self.assertEqual(evidence["repo_dirty"], dirty)
        actual_head, actual_dirty = repo_provenance()
        self.assertIsInstance(actual_head, str)
        self.assertIn(actual_dirty, (True, False, None))
        if actual_head == "unknown":
            self.assertIsNone(actual_dirty)

    def test_provenance_is_sampled_before_evidence_creates_an_untracked_file(self):
        observed = []
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence.jsonl"
            def provenance(path=None):
                observed.append((evidence.exists(), path))
                return ("0" * 40, False)
            old_stdout, sys.stdout = sys.stdout, io.StringIO()
            try:
                with mock.patch.object(mincore_uart, "repo_provenance", provenance):
                    self.assertEqual(main(["--operation", "set", "--vector", "set128",
                                           "--dry-run", "--evidence", str(evidence)]), 0)
            finally:
                sys.stdout = old_stdout
            record = json.loads(evidence.read_text())
        self.assertEqual(observed, [(False, evidence)])
        self.assertFalse(record["repo_dirty"])

    def test_appending_evidence_inside_the_checkout_never_reports_dirty(self):
        root = Path(__file__).resolve().parents[3]
        evidence = root / "test_evidence_provenance_probe.jsonl"
        self.addCleanup(evidence.unlink, True)
        self.assertFalse(evidence.exists())
        before = repo_provenance(evidence)
        evidence.write_text('{"probe": true}\n')
        self.assertEqual(repo_provenance(evidence), before)
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / "evidence.jsonl"
            outside.write_text("")
            self.assertEqual(repo_provenance(outside), repo_provenance())

    def test_transport_failure_is_not_retried(self):
        class BrokenSerial(FakeSerial):
            def write(self, data):
                raise OSError("link lost")
        with self.assertRaisesRegex(TransportFailure, "not retried"):
            MinCoreDriver(BrokenSerial(), .2, Clock()).exchange("status")

    def test_cli_rejects_nonphysical_mode_mixed_with_execute(self):
        with self.assertRaises(SystemExit) as stopped:
            main(["--execute", "--port", "opaque", "--encode"])
        self.assertEqual(stopped.exception.code, 2)
        for option, value in (("--timeout", "nan"), ("--timeout", "0"),
                              ("--baud", "0"), ("--baud", "4000001")):
            with self.assertRaises(SystemExit) as stopped:
                main([option, value])
            self.assertEqual(stopped.exception.code, 2)

    def test_encode_and_dry_run_do_not_fabricate_a_response(self):
        output = io.StringIO()
        old_stdout, sys.stdout = sys.stdout, output
        try:
            self.assertEqual(main(["--operation", "mul", "--vector", "mul128", "--encode"]), 0)
        finally:
            sys.stdout = old_stdout
        result = json.loads(output.getvalue())
        self.assertEqual(result["response_hex"], "")
        self.assertIsNone(result["pass"])
        self.assertFalse(result["execution_attempted"])
        self.assertFalse(result["serial_response_observed"])

    def test_decode_only_does_not_require_or_encode_request_operands(self):
        output = io.StringIO()
        old_stdout, sys.stdout = sys.stdout, output
        try:
            self.assertEqual(main(["--operation", "set", "--decode", VECTORS["set128"].expected.hex()]), 0)
        finally:
            sys.stdout = old_stdout
        result = json.loads(output.getvalue())
        self.assertEqual(result["request_hex"], "")
        self.assertEqual(result["response_hex"], VECTORS["set128"].expected.hex())
        self.assertIsNone(result["pass"])

    def test_consecutive_commands_response_validation_and_evidence_redaction(self):
        serial = FakeSerial(read_limit=2, responses=(STATUS_BYTES, VECTORS["mul128"].expected))
        driver = MinCoreDriver(serial, .2, Clock())
        self.assertEqual(driver.exchange("status")[1], STATUS_BYTES)
        request, actual = driver.exchange("mul", a=VECTORS["mul128"].a, b=VECTORS["mul128"].b)
        self.assertEqual(actual, VECTORS["mul128"].expected)
        output = io.BytesIO()
        record_evidence(output, provenance=("0" * 40, False), operation="mul", request=request,
                        response=actual, expected=actual, passed=True,
                        execution_attempted=False, serial_response_observed=False)
        evidence = json.loads(output.getvalue())
        self.assertNotIn("port", evidence)
        self.assertNotIn("request_hex", evidence)
        self.assertNotIn("response_hex", evidence)
        self.assertEqual(evidence["request_length"], len(request))
        self.assertFalse(evidence["execution_attempted"])
        self.assertFalse(evidence["serial_response_observed"])
        self.assertTrue(evidence["pass"])


if __name__ == "__main__": unittest.main()

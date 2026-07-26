from __future__ import annotations

import argparse
import math
import threading
import time
import unittest

from fpga_harness.host.lsc1_packet_uart import (
    PacketSerialDriver,
    PacketTransportError,
    _instruction_frame,
    _validate_instruction_result,
    _validate_retired,
    _validate_capabilities,
    protocol,
)


class FakeTransport:
    def __init__(self, response: bytes, *, write_limit: int = 3, read_limit: int = 2):
        self.pending_response = bytes(response)
        self.response = bytearray()
        self.written = bytearray()
        self.write_limit = write_limit
        self.read_limit = read_limit
        self.timeout = 1.0
        self.breaks = 0

    @property
    def in_waiting(self) -> int:
        return len(self.response)

    def write(self, data: bytes) -> int:
        count = min(len(data), self.write_limit)
        self.written.extend(data[:count])
        return count

    def read(self, size: int) -> bytes:
        count = min(size, self.read_limit, len(self.response))
        data = bytes(self.response[:count])
        del self.response[:count]
        return data

    def flush(self) -> None:
        if not self.response:
            self.response.extend(self.pending_response)

    def send_break(self, duration: float) -> None:
        self.breaks += 1


class PacketSerialDriverTests(unittest.TestCase):
    def test_timeout_must_be_positive_and_finite(self) -> None:
        for timeout in (0.0, -1.0, math.inf, math.nan):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                PacketSerialDriver(FakeTransport(b""), timeout=timeout)

    def test_preflight_drain_is_bounded_by_exchange_deadline(self) -> None:
        blocker = threading.Event()

        class BlockingTransport(FakeTransport):
            @property
            def in_waiting(self) -> int:
                blocker.wait()
                return 0

        transport = BlockingTransport(b"")
        started = time.monotonic()
        with self.assertRaisesRegex(PacketTransportError, "drain deadline"):
            PacketSerialDriver(transport, timeout=0.02).exchange_encoded(b"x")
        self.assertLess(time.monotonic() - started, 0.2)

    def test_packet_rtl_capability_subset_is_explicit(self) -> None:
        payload = (
            bytes((1, 1)) + (256).to_bytes(2, "little") + bytes((16, 0))
            + (2).to_bytes(4, "little") + (0x4C534331).to_bytes(4, "little")
        )
        _validate_capabilities(payload, protocol.Profile.INTERPRETER_COMPAT)
        with self.assertRaises(PacketTransportError):
            _validate_capabilities(payload[:6] + bytes(8), protocol.Profile.INTERPRETER_COMPAT)

    def test_partial_reads_and_writes_preserve_the_exact_frame(self) -> None:
        request = protocol.build_status_query()
        response = protocol.ResponseFrame(protocol.Status.INFO, bytes(20)).encode()
        transport = FakeTransport(response)
        decoded = PacketSerialDriver(transport).exchange(request)
        self.assertEqual(bytes(transport.written), request.encode())
        self.assertEqual(decoded, protocol.ResponseFrame(protocol.Status.INFO, bytes(20)))

    def test_surplus_response_bytes_are_rejected(self) -> None:
        response = protocol.ResponseFrame(protocol.Status.INFO, bytes(20)).encode() + b"x"
        with self.assertRaisesRegex(PacketTransportError, "surplus"):
            PacketSerialDriver(FakeTransport(response)).exchange(protocol.build_status_query())

    def test_encoded_exchange_preserves_malformed_test_vector(self) -> None:
        request = bytearray(protocol.build_status_query().encode())
        request[-1] ^= 1
        response = protocol.ResponseFrame(protocol.Status.BAD_CRC, bytes(5)).encode()
        transport = FakeTransport(response)
        decoded = PacketSerialDriver(transport).exchange_encoded(bytes(request))
        self.assertEqual(bytes(transport.written), request)
        self.assertIs(decoded.status, protocol.Status.BAD_CRC)

    def test_uart_break_is_the_packet_safe_abort(self) -> None:
        transport = FakeTransport(b"")
        PacketSerialDriver(transport).abort()
        self.assertEqual(transport.breaks, 1)

    def test_instruction_builders_use_independent_field_oracles(self) -> None:
        for operation, expected in (("set", 7), ("xor", 3 ^ 5),
                                    ("mul", protocol.field_mul(3, 5))):
            args = argparse.Namespace(
                operation=operation, txn_id=9, pc=0, fp=0,
                value=7, a=3, b=5,
            )
            frame, result = _instruction_frame(args)
            self.assertEqual(result, expected)
            self.assertEqual(frame.payload[:4], (9).to_bytes(4, "little"))

    def test_result_validation_binds_the_complete_scalar_transition(self) -> None:
        args = argparse.Namespace(operation="xor", txn_id=9, pc=7, fp=11)
        expected = 3 ^ 5
        valid = {
            "next_pc": 8,
            "next_fp": 11,
            "writes": [{"address": 13, "value": expected}],
            "deferred": [],
            "accesses": [11, 12, 13],
        }
        _validate_instruction_result(valid, args, expected)
        for field, bad_value in (
            ("next_pc", 9),
            ("next_fp", 12),
            ("writes", [{"address": 12, "value": expected}]),
            ("deferred", [{"target": 11, "local": 12}]),
            ("accesses", [11, 12]),
        ):
            with self.subTest(field=field), self.assertRaises(PacketTransportError):
                _validate_instruction_result(valid | {field: bad_value}, args, expected)

    def test_retired_validation_binds_transaction_and_committed_state(self) -> None:
        args = argparse.Namespace(txn_id=9, pc=7, fp=11)
        payload = (
            (9).to_bytes(4, "little")
            + (1).to_bytes(4, "little")
            + (8).to_bytes(4, "little")
            + (11).to_bytes(4, "little")
        )
        _validate_retired(protocol.ResponseFrame(protocol.Status.RETIRED, payload), args)
        for changed in (
            payload[:-1],
            (10).to_bytes(4, "little") + payload[4:],
            payload[:8] + (9).to_bytes(4, "little") + payload[12:],
            payload[:12] + (12).to_bytes(4, "little"),
        ):
            with self.assertRaises(PacketTransportError):
                _validate_retired(
                    protocol.ResponseFrame(protocol.Status.RETIRED, changed), args
                )


if __name__ == "__main__":
    unittest.main()

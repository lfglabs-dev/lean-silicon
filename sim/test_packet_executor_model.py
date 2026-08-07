"""Adversarial and differential tests for the Phase-3 packet executor."""

from __future__ import annotations

import random
import unittest

import lsc1_transaction as reference
import scalar_step_oracle as scalar
from packet_executor_model import (
    FUTURE_GAPS,
    MAX_REQUEST_BYTES,
    PacketExecutor,
    State,
    Status,
    crc32,
    multiply,
)


def frame(opcode: int, payload: bytes, *, version: int = 1, flags: int = 0) -> bytes:
    body = bytes((0xA1, version, opcode, flags))
    body += len(payload).to_bytes(2, "little") + payload
    return body + crc32(body).to_bytes(4, "little")


def retire(txn_id: int, result_crc: int) -> bytes:
    return frame(0x12, txn_id.to_bytes(4, "little") + result_crc.to_bytes(4, "little"))


def decode_response(encoded: bytes) -> tuple[int, bytes]:
    assert encoded[0] == 0x5A
    length = int.from_bytes(encoded[3:5], "little")
    assert len(encoded) == 5 + length + 4
    assert int.from_bytes(encoded[-4:], "little") == crc32(encoded[:-4])
    return encoded[2], encoded[5:-4]


def split_responses(stream: bytes) -> list[bytes]:
    responses = []
    position = 0
    while position < len(stream):
        length = int.from_bytes(stream[position + 3 : position + 5], "little")
        end = position + 5 + length + 4
        responses.append(stream[position:end])
        position = end
    return responses


def drive_request(
    endpoint,
    request: bytes,
    *,
    rx_stalls: set[int] | None = None,
    tx_pattern: tuple[bool, ...] = (True,),
    done_samples: list[bool] | None = None,
) -> bytes:
    rx_stalls = rx_stalls or set()
    sent = 0
    cycle = 0
    response = bytearray()
    while sent < len(request) or endpoint.pins().tx_valid:
        rx_valid = sent < len(request) and cycle not in rx_stalls
        tx_ready = tx_pattern[cycle % len(tx_pattern)]
        record = endpoint.step(
            rx_data=request[sent] if sent < len(request) else 0,
            rx_valid=rx_valid,
            tx_ready=tx_ready,
        )
        if done_samples is not None:
            done_samples.append(record.pins.done_pulse)
        if record.rx_committed:
            sent += 1
        if record.tx_committed:
            response.append(record.pins.tx_data)
        cycle += 1
        if cycle > 10000:
            raise AssertionError("driver timeout")
    return bytes(response)


def cell(present: bool, value: int = 0) -> bytes:
    return bytes((int(present),)) + value.to_bytes(16, "little")


def preamble(txn_id: int, pc: int = 0, fp: int = 0, profile: int = 1) -> bytes:
    return (
        txn_id.to_bytes(4, "little")
        + pc.to_bytes(4, "little")
        + fp.to_bytes(4, "little")
        + bytes((profile, 0))
    )


def set_request(txn_id: int, offset: int, value: int, old=None, *, pc=0, fp=0) -> bytes:
    payload = preamble(txn_id, pc, fp)
    payload += offset.to_bytes(4, "little") + value.to_bytes(16, "little")
    payload += cell(old is not None, old or 0)
    return frame(0x03, payload)


def binary_request(
    opcode: int,
    txn_id: int,
    offsets: tuple[int, int, int],
    values: tuple[int | None, int | None, int | None],
    *,
    inverse: int | None = None,
    pc: int = 0,
    fp: int = 0,
    profile: int = 1,
) -> bytes:
    payload = preamble(txn_id, pc, fp, profile)
    payload += b"".join(offset.to_bytes(4, "little") for offset in offsets)
    payload += b"".join(cell(value is not None, value or 0) for value in values)
    if opcode == 0x02:
        payload += cell(inverse is not None, inverse or 0)
    return frame(opcode, payload)


class PacketExecutorTests(unittest.TestCase):
    def assert_differential(self, request: bytes) -> tuple[PacketExecutor, bytes]:
        candidate = PacketExecutor()
        expected = reference.Lsc1Endpoint()
        candidate_response = drive_request(candidate, request, tx_pattern=(False, True, False, True))
        reference_response = drive_request(expected, request, tx_pattern=(False, True, False, True))
        self.assertEqual(candidate_response, reference_response)
        return candidate, candidate_response

    def test_bad_fixed_length_echoes_the_available_transaction_id_prefix(self):
        complete = preamble(0x44332228) + b"\x00" * 36
        for payload, echoed in (
            (complete, 0x44332228),
            (b"\x28\x22\x33", 0x00332228),
            (b"", 0),
        ):
            with self.subTest(payload_length=len(payload)):
                request = frame(0x03, payload)
                _, response = self.assert_differential(request)
                status, fault_payload = decode_response(response)
                self.assertEqual(status, Status.BAD_LENGTH)
                self.assertEqual(int.from_bytes(fault_payload[:4], "little"), echoed)
                self.assertEqual(fault_payload[4], 2)

    def test_source_located_future_gap_table_is_explicit_and_non_executable(self):
        self.assertEqual(
            [gap.feature for gap in FUTURE_GAPS],
            ["DEREF", "JUMP", "witness/deferred equality", "BLAKE3"],
        )
        for gap in FUTURE_GAPS:
            self.assertIn("docs/LSC1_TRANSACTION_PROTOCOL.md", gap.wire_source)
            self.assertIn("c308034a", gap.semantic_source)
            self.assertTrue(gap.reason)

    def test_future_and_unknown_opcodes_are_deterministically_unsupported(self):
        for opcode in (0x04, 0x05, 0x06, 0x07, 0x08, 0x10, 0x11, 0x13, 0xFE):
            candidate = decode_response(drive_request(PacketExecutor(), frame(opcode, b"")))
            self.assertEqual(candidate[0], Status.BAD_OPCODE)
        unknown = frame(0xFE, b"")
        self.assertEqual(
            drive_request(PacketExecutor(), unknown),
            drive_request(reference.Lsc1Endpoint(), unknown),
        )

    def test_little_endian_set_constant_and_atomic_retirement(self):
        endpoint = PacketExecutor()
        value = 0xFFEEDDCCBBAA99887766554433221100
        response = drive_request(endpoint, set_request(0x78563412, 0x01020304, value))
        status, payload = decode_response(response)
        self.assertEqual(status, Status.OK)
        self.assertEqual(payload[:4], b"\x12\x34\x56\x78")
        self.assertEqual(payload[13:17], b"\x04\x03\x02\x01")
        self.assertEqual(payload[17:33], value.to_bytes(16, "little"))
        self.assertEqual((endpoint.committed_pc, endpoint.retire_seq), (0, 0))
        result_crc = crc32(payload)
        retired = drive_request(endpoint, retire(0x78563412, result_crc))
        self.assertEqual(decode_response(retired)[0], Status.RETIRED)
        self.assertEqual((endpoint.committed_pc, endpoint.committed_fp), (1, 0))
        self.assertEqual(endpoint.retire_seq, 1)

    def test_retirement_and_done_pulse_are_end_to_end_differential(self):
        candidate = PacketExecutor()
        expected = reference.Lsc1Endpoint()
        request = set_request(0xA0B0C0D0, 7, 0x112233445566778899AABBCCDDEEFF00)
        candidate_result = drive_request(candidate, request)
        expected_result = drive_request(expected, request)
        self.assertEqual(candidate_result, expected_result)
        result_payload = decode_response(candidate_result)[1]
        retirement = retire(0xA0B0C0D0, crc32(result_payload))

        candidate_done, expected_done = [], []
        candidate_retired = drive_request(
            candidate, retirement, tx_pattern=(False, True), done_samples=candidate_done
        )
        expected_retired = drive_request(
            expected, retirement, tx_pattern=(False, True), done_samples=expected_done
        )
        self.assertEqual(candidate_retired, expected_retired)
        self.assertEqual(candidate_done, expected_done)
        self.assertEqual(sum(candidate_done), 1)
        self.assertEqual(
            (candidate.committed_pc, candidate.committed_fp, candidate.retire_seq),
            (expected.committed_pc, expected.committed_fp, expected.retire_seq),
        )
        # The driver consumed the response, so DONE has already appeared for
        # exactly its first drain cycle and must now be low on both endpoints.
        self.assertFalse(candidate.pins().done_pulse)
        self.assertFalse(expected.pins().done_pulse)

    def test_decoded_transaction_id_survives_malformed_preamble(self):
        for position, status in ((18, Status.BAD_PROFILE), (19, Status.BAD_FLAGS)):
            request = bytearray(set_request(0x44332211, 0, 1))
            request[position] = 2 if status is Status.BAD_PROFILE else 1
            request[-4:] = crc32(request[:-4]).to_bytes(4, "little")
            candidate = drive_request(PacketExecutor(), bytes(request))
            expected = drive_request(reference.Lsc1Endpoint(), bytes(request))
            actual_status, payload = decode_response(candidate)
            self.assertEqual(decode_response(expected)[0], actual_status)
            self.assertEqual((actual_status, payload[:4]), (status, b"\x11\x22\x33\x44"))

    def test_malformed_payload_precedes_result_pending_state_guard(self):
        candidate, expected = PacketExecutor(), reference.Lsc1Endpoint()
        first = set_request(1, 0, 1)
        self.assertEqual(drive_request(candidate, first), drive_request(expected, first))
        malformed = bytearray(set_request(0x44332211, 0, 1))
        malformed[40] = 2
        malformed[-4:] = crc32(malformed[:-4]).to_bytes(4, "little")
        candidate_response = drive_request(candidate, bytes(malformed))
        expected_response = drive_request(expected, bytes(malformed))
        status, payload = decode_response(candidate_response)
        self.assertEqual(decode_response(expected_response)[0], status)
        self.assertEqual((status, payload[:4]), (Status.BAD_CELL, b"\x11\x22\x33\x44"))

    def test_seeded_random_differential_and_scalar_oracle(self):
        rng = random.Random(0xC308034A)
        edges = [0, 1, 2, 0x87, 1 << 127, (1 << 128) - 1]
        for case in range(40):
            left = rng.getrandbits(128) if case >= len(edges) else edges[case]
            right = rng.getrandbits(128) if case + 1 >= len(edges) else edges[case + 1]
            opcode = 0x01 if case % 2 == 0 else 0x02
            request = binary_request(opcode, case + 1, (3, 5, 7), (left, right, None))
            candidate, response = self.assert_differential(request)
            payload = decode_response(response)[1]
            actual = int.from_bytes(payload[17:33], "little")
            machine = scalar.Machine(memory={3: left, 5: right}, written={3, 5})
            machine.step(("xor" if opcode == 0x01 else "mul", 3, 5, 7))
            self.assertEqual(actual, machine.memory[7])
            self.assertEqual(candidate.staged.writes[0].value, machine.memory[7])

    def test_gf128_edge_vectors_and_algebraic_metamorphisms(self):
        values = [0, 1, 2, 0x87, 1 << 127, (1 << 128) - 1]
        for left in values:
            for right in values:
                self.assertEqual(multiply(left, right), scalar.multiply(left, right))
                self.assertEqual(multiply(left, right), multiply(right, left))
                self.assertEqual(multiply(left, right ^ 1), multiply(left, right) ^ left)
            self.assertEqual(multiply(left, 0), 0)
            self.assertEqual(multiply(left, 1), left)

    def test_backsolve_xor_and_mul_match_reference(self):
        xor = binary_request(0x01, 11, (1, 2, 3), (None, 0xAA, 0x55))
        self.assert_differential(xor)
        known = 0x123456789
        product = 0xABCDEF
        inverse = scalar.inverse(known)
        mul = binary_request(0x02, 12, (1, 2, 3), (None, known, product), inverse=inverse)
        self.assert_differential(mul)

    def test_stalls_and_output_backpressure_are_byte_exact(self):
        request = set_request(3, 9, 0xA5)
        baseline = drive_request(PacketExecutor(), request)
        stalled = drive_request(
            PacketExecutor(),
            request,
            rx_stalls={0, 2, 4, 7, 12, 20, 35},
            tx_pattern=(False, False, True, False, True),
        )
        self.assertEqual(stalled, baseline)

    def test_output_drain_poisoning_cannot_inject_next_request(self):
        endpoint = PacketExecutor()
        first = set_request(1, 4, 8)
        for byte in first:
            self.assertTrue(endpoint.step(rx_data=byte, rx_valid=True).rx_committed)
        held = endpoint.pins()
        self.assertTrue(held.tx_valid)
        poison = endpoint.step(rx_data=0xA1, rx_valid=True, tx_ready=False)
        self.assertFalse(poison.rx_committed)
        self.assertEqual(poison.pins.tx_data, held.tx_data)
        self.assertEqual(endpoint.buffered_bytes, 0)
        response = bytearray()
        while endpoint.pins().tx_valid:
            record = endpoint.step(tx_ready=True)
            if record.tx_committed:
                response.append(record.pins.tx_data)
        self.assertEqual(decode_response(bytes(response))[0], Status.OK)

    def test_abort_wins_over_rx_tx_and_preserves_committed_state(self):
        endpoint = PacketExecutor()
        result = decode_response(drive_request(endpoint, set_request(1, 1, 2)))[1]
        drive_request(endpoint, retire(1, crc32(result)))
        self.assertEqual(endpoint.committed_pc, 1)
        partial = set_request(2, 2, 3, pc=1)
        for byte in partial[:20]:
            endpoint.step(rx_data=byte, rx_valid=True)
        record = endpoint.step(rx_data=partial[20], rx_valid=True, tx_ready=True, abort=True)
        self.assertFalse(record.rx_committed)
        self.assertFalse(record.tx_committed)
        self.assertEqual(endpoint.state, State.IDLE)
        self.assertEqual((endpoint.committed_pc, endpoint.retire_seq), (1, 1))
        self.assertEqual(endpoint.last_status, Status.ABORTED)

    def test_reset_wins_and_clears_everything(self):
        endpoint = PacketExecutor()
        drive_request(endpoint, set_request(1, 0, 1))
        record = endpoint.step(rx_data=0xA1, rx_valid=True, tx_ready=True, abort=True, reset_n=False)
        self.assertFalse(record.rx_committed)
        self.assertFalse(record.tx_committed)
        self.assertEqual(endpoint.state, State.IDLE)
        self.assertEqual((endpoint.committed_pc, endpoint.retire_seq), (0, 0))
        self.assertFalse(endpoint.state_valid)
        self.assertFalse(endpoint.pins().fault)

    def test_foreign_duplicate_and_bad_crc_retire_ids(self):
        endpoint = PacketExecutor()
        payload = decode_response(drive_request(endpoint, set_request(7, 0, 9)))[1]
        foreign = decode_response(drive_request(endpoint, retire(8, crc32(payload))))
        self.assertEqual((foreign[0], foreign[1][:4], foreign[1][4]), (Status.RETIRE_MISMATCH, b"\x08\0\0\0", 1))
        self.assertEqual((endpoint.committed_pc, endpoint.retire_seq), (0, 0))
        duplicate = decode_response(drive_request(endpoint, retire(7, crc32(payload))))
        self.assertEqual(duplicate[0], Status.BAD_STATE)

        payload = decode_response(drive_request(endpoint, set_request(9, 0, 9)))[1]
        wrong_crc = decode_response(drive_request(endpoint, retire(9, crc32(payload) ^ 1)))
        self.assertEqual((wrong_crc[0], wrong_crc[1][4]), (Status.RETIRE_MISMATCH, 2))
        self.assertEqual(endpoint.retire_seq, 0)

    def test_duplicate_instruction_preserves_staged_transaction(self):
        endpoint = PacketExecutor()
        original_payload = decode_response(drive_request(endpoint, set_request(41, 1, 2)))[1]
        duplicate = decode_response(drive_request(endpoint, set_request(41, 1, 2)))
        self.assertEqual(duplicate[0], Status.BAD_STATE)
        self.assertEqual(endpoint.staged.txn_id, 41)
        retired = drive_request(endpoint, retire(41, crc32(original_payload)))
        self.assertEqual(decode_response(retired)[0], Status.RETIRED)

    def test_truncation_requires_abort_and_extra_bytes_are_separate_frames(self):
        endpoint = PacketExecutor()
        request = set_request(1, 0, 3)
        for byte in request[:-1]:
            endpoint.step(rx_data=byte, rx_valid=True)
        self.assertFalse(endpoint.pins().tx_valid)
        self.assertGreater(endpoint.buffered_bytes, 0)
        endpoint.step(abort=True)
        self.assertEqual(endpoint.buffered_bytes, 0)
        self.assertEqual(decode_response(drive_request(endpoint, request))[0], Status.OK)

        endpoint = PacketExecutor()
        response = drive_request(endpoint, request + b"\x00")
        responses = split_responses(response)
        self.assertEqual([decode_response(item)[0] for item in responses], [Status.OK, Status.BAD_SOF])
        # The extra byte cannot commit until the first response has drained;
        # once it does commit, it is deterministically treated as a new frame.
        self.assertEqual(endpoint.buffered_bytes, 0)

    def test_malformed_headers_lengths_crc_flags_cells_and_opcode(self):
        good = bytearray(set_request(0x44332211, 0, 1))
        cases: list[tuple[bytes, Status]] = []
        bad = bytearray(good)
        bad[0] = 0
        cases.append((bytes(bad[:1]), Status.BAD_SOF))
        bad = bytearray(good)
        bad[1] = 2
        bad[-4:] = crc32(bad[:-4]).to_bytes(4, "little")
        cases.append((bytes(bad), Status.BAD_VERSION))
        bad = bytearray(good)
        bad[2] = 0xFE
        bad[-4:] = crc32(bad[:-4]).to_bytes(4, "little")
        cases.append((bytes(bad), Status.BAD_OPCODE))
        bad = bytearray(good)
        bad[3] = 1
        bad[-4:] = crc32(bad[:-4]).to_bytes(4, "little")
        cases.append((bytes(bad), Status.BAD_FLAGS))
        bad = bytearray(good)
        bad[-1] ^= 1
        cases.append((bytes(bad), Status.BAD_CRC))
        bad = bytearray(good)
        bad[4:6] = (257).to_bytes(2, "little")
        cases.append((bytes(bad[:6]), Status.BAD_LENGTH))
        bad = bytearray(good)
        bad[4:6] = (50).to_bytes(2, "little")
        bad = bad[:56] + crc32(bad[:56]).to_bytes(4, "little")
        cases.append((bytes(bad), Status.BAD_LENGTH))
        bad = bytearray(good)
        bad[40] = 2  # SET_CONSTANT cell presence byte
        bad[-4:] = crc32(bad[:-4]).to_bytes(4, "little")
        cases.append((bytes(bad), Status.BAD_CELL))
        for encoded, expected in cases:
            status, _ = decode_response(drive_request(PacketExecutor(), encoded))
            self.assertEqual(status, expected)

    def test_seeded_single_byte_mutations_never_commit_state(self):
        rng = random.Random(0x5041434B4554)
        original = set_request(0x1234, 6, 0xDEADBEEF)
        for _ in range(80):
            mutated = bytearray(original)
            position = rng.randrange(len(mutated))
            mutated[position] ^= 1 << rng.randrange(8)
            endpoint = PacketExecutor()
            response = drive_request(endpoint, bytes(mutated))
            if response:
                statuses = [decode_response(item)[0] for item in split_responses(response)]
                self.assertTrue(all(status >= 0x80 for status in statuses))
            else:
                # A mutated in-cap length may make a syntactically truncated
                # frame.  The contract requires timeout+ABORT recovery.
                self.assertGreater(endpoint.buffered_bytes, 0)
                endpoint.step(abort=True)
                self.assertEqual(endpoint.buffered_bytes, 0)
            self.assertEqual((endpoint.committed_pc, endpoint.retire_seq), (0, 0))
            self.assertIsNone(endpoint.staged)
            self.assertLessEqual(endpoint.buffered_bytes, MAX_REQUEST_BYTES)

    def test_state_mismatch_rollback_after_successful_retirement(self):
        endpoint = PacketExecutor()
        payload = decode_response(drive_request(endpoint, set_request(1, 0, 1)))[1]
        drive_request(endpoint, retire(1, crc32(payload)))
        fault = decode_response(drive_request(endpoint, set_request(2, 0, 2, pc=0)))
        self.assertEqual(fault[0], Status.STATE_MISMATCH)
        self.assertEqual((endpoint.committed_pc, endpoint.retire_seq), (1, 1))
        self.assertIsNone(endpoint.staged)

    def test_execution_fault_rollback_is_differential_and_reusable(self):
        candidate = PacketExecutor()
        expected = reference.Lsc1Endpoint()
        conflict = set_request(55, 3, 0xAA, old=0xBB)
        self.assertEqual(
            drive_request(candidate, conflict),
            drive_request(expected, conflict),
        )
        self.assertEqual((candidate.state, candidate.staged), (State.IDLE, None))
        self.assertEqual((expected.state.value, expected.staged), ("idle", None))
        self.assertEqual(
            (candidate.committed_pc, candidate.committed_fp, candidate.retire_seq),
            (expected.committed_pc, expected.committed_fp, expected.retire_seq),
        )
        valid = set_request(56, 3, 0xAA)
        self.assertEqual(drive_request(candidate, valid), drive_request(expected, valid))


if __name__ == "__main__":
    unittest.main()

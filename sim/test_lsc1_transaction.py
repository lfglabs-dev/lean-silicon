"""Deterministic tests for the LSC-1 transaction protocol codec and model.

Every check that matters is made against an *independent* computation: the
field product is recomputed by carry-less multiply plus long reduction (the
module accumulates through ``xtime``), ``g**n`` is recomputed by naive repeated
``xtime`` (the module squares and multiplies), and the frame CRC is recomputed
by ``zlib`` (the module runs a bit-at-a-time register).  No oracle used here
calls the implementation it is checking.
"""

from __future__ import annotations

import random
import unittest
import zlib

import lsc1_transaction as lsc1
from lsc1_transaction import (
    ABSENT,
    CRC_BYTES,
    MASK128,
    MAX_PAYLOAD_BYTES,
    PROTOCOL_VERSION,
    REQUEST_HEADER_BYTES,
    REQUEST_PAYLOAD_BYTES,
    RESPONSE_HEADER_BYTES,
    SOF_REQUEST,
    SOF_RESPONSE,
    U32_MAX,
    Cell,
    Lsc1Endpoint,
    Opcode,
    Profile,
    ProtocolFault,
    Status,
    TxnState,
)

SEED = 0x15C1


# --- Independent oracles. ---------------------------------------------------


def ref_mul(left: int, right: int) -> int:
    """Carry-less product then long reduction by x^128 + x^7 + x^2 + x + 1."""
    product = 0
    for bit in range(128):
        if (right >> bit) & 1:
            product ^= left << bit
    for bit in reversed(range(128, 256)):
        if (product >> bit) & 1:
            product ^= (1 << bit) | (0x87 << (bit - 128))
    return product & MASK128


def ref_encode(index: int) -> int:
    """``g**index`` by naive repeated multiplication by the generator."""
    value = 1
    for _ in range(index):
        value = (value << 1) & MASK128 ^ (0x87 if value >> 127 else 0)
    return value


def ref_crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


# --- Shared helpers. --------------------------------------------------------


def exchange(endpoint: Lsc1Endpoint, frame: lsc1.RequestFrame) -> lsc1.ResponseFrame:
    """Push one request through the lane at full rate and decode the reply."""
    response, _ = lsc1.drive(endpoint, frame.encode())
    return lsc1.decode_response(response)


def negotiated(profile: Profile) -> Lsc1Endpoint:
    endpoint = Lsc1Endpoint()
    reply = exchange(endpoint, lsc1.build_negotiate(profile=profile))
    assert reply.status is Status.OK
    return endpoint


def simple_xor(txn_id: int = 1, pc: int = 0, fp: int = 64) -> lsc1.RequestFrame:
    return lsc1.build_binary_op(
        Opcode.XOR,
        txn_id=txn_id,
        pc=pc,
        fp=fp,
        profile=Profile.INTERPRETER_COMPAT,
        offsets=(1, 2, 3),
        cells=(Cell(True, 0xDEAD), Cell(True, 0xBEEF), ABSENT),
    )


def retire(endpoint: Lsc1Endpoint) -> lsc1.ResponseFrame:
    staged = endpoint.staged
    assert staged is not None
    return exchange(
        endpoint, lsc1.build_retire(txn_id=staged.txn_id, result_crc=staged.result_crc)
    )


def pointer_cell(base: int) -> Cell:
    return Cell(True, ref_encode(base))


# --- Field arithmetic and CRC. ----------------------------------------------


class FieldArithmeticTests(unittest.TestCase):
    def test_multiply_matches_carryless_reduction_oracle(self) -> None:
        rng = random.Random(SEED)
        for _ in range(64):
            left = rng.getrandbits(128)
            right = rng.getrandbits(128)
            self.assertEqual(lsc1.field_mul(left, right), ref_mul(left, right))

    def test_multiply_identities(self) -> None:
        rng = random.Random(SEED + 1)
        for _ in range(16):
            value = rng.getrandbits(128)
            self.assertEqual(lsc1.field_mul(value, 1), value)
            self.assertEqual(lsc1.field_mul(value, 0), 0)
            self.assertEqual(lsc1.field_mul(value, 2), lsc1.field_xtime(value))

    def test_encode_matches_naive_generator_powers(self) -> None:
        for index in [0, 1, 2, 3, 7, 127, 128, 129, 1000, 4097, lsc1.INDEX_LIMIT - 1]:
            self.assertEqual(lsc1.field_encode(index), ref_encode(index))

    def test_encode_is_a_group_homomorphism(self) -> None:
        rng = random.Random(SEED + 2)
        for _ in range(32):
            a = rng.randrange(0, 1 << 14)
            b = rng.randrange(0, 1 << 14)
            self.assertEqual(
                lsc1.field_encode(a + b),
                ref_mul(lsc1.field_encode(a), lsc1.field_encode(b)),
            )

    def test_encode_rejects_out_of_range_indices(self) -> None:
        for index in (-1, lsc1.INDEX_LIMIT, lsc1.INDEX_LIMIT + 1):
            with self.assertRaises(ProtocolFault) as caught:
                lsc1.field_encode(index)
            self.assertIs(caught.exception.status, Status.INDEX_RANGE)

    def test_checked_add_faults_instead_of_wrapping(self) -> None:
        self.assertEqual(lsc1.checked_add(U32_MAX - 1, 1), U32_MAX)
        with self.assertRaises(ProtocolFault) as caught:
            lsc1.checked_add(U32_MAX, 1)
        self.assertIs(caught.exception.status, Status.U32_OVERFLOW)

    def test_crc32_matches_zlib(self) -> None:
        rng = random.Random(SEED + 3)
        cases = [b"", b"\x00", b"lean-silicon", bytes(range(256))]
        cases += [bytes(rng.getrandbits(8) for _ in range(rng.randrange(1, 64))) for _ in range(32)]
        for data in cases:
            self.assertEqual(lsc1.crc32(data), ref_crc32(data))


# --- Frame codec. -----------------------------------------------------------


class FrameCodecTests(unittest.TestCase):
    def test_request_frame_sizes_are_envelope_plus_declared_payload(self) -> None:
        for opcode, payload_bytes in REQUEST_PAYLOAD_BYTES.items():
            expected = REQUEST_HEADER_BYTES + payload_bytes + CRC_BYTES
            self.assertEqual(lsc1.request_frame_bytes(opcode), expected)
            self.assertLessEqual(payload_bytes, MAX_PAYLOAD_BYTES)

    def test_every_builder_emits_its_declared_payload_length(self) -> None:
        for frame in all_request_frames():
            with self.subTest(opcode=frame.opcode.name):
                encoded = frame.encode()
                self.assertEqual(len(frame.payload), REQUEST_PAYLOAD_BYTES[frame.opcode])
                self.assertEqual(len(encoded), lsc1.request_frame_bytes(frame.opcode))
                self.assertEqual(encoded[0], SOF_REQUEST)
                self.assertEqual(encoded[1], PROTOCOL_VERSION)
                self.assertEqual(encoded[2], int(frame.opcode))
                self.assertEqual(int.from_bytes(encoded[4:6], "little"), len(frame.payload))
                self.assertEqual(
                    int.from_bytes(encoded[-CRC_BYTES:], "little"),
                    ref_crc32(encoded[:-CRC_BYTES]),
                )

    def test_request_payload_round_trips_through_the_decoder(self) -> None:
        for frame in all_request_frames():
            with self.subTest(opcode=frame.opcode.name):
                decoded = lsc1.decode_request_payload(frame.opcode, frame.payload)
                self.assertIs(decoded.opcode, frame.opcode)

    def test_response_frame_round_trip(self) -> None:
        payload = bytes(range(32))
        frame = lsc1.ResponseFrame(Status.OK, payload)
        decoded = lsc1.decode_response(frame.encode())
        self.assertIs(decoded.status, Status.OK)
        self.assertEqual(decoded.payload, payload)
        self.assertEqual(len(frame.encode()), lsc1.response_frame_bytes(len(payload)))

    def test_response_decoder_rejects_malformation(self) -> None:
        good = lsc1.ResponseFrame(Status.OK, b"\x01\x02").encode()
        cases = {
            Status.BAD_LENGTH: good[:-1],
            Status.BAD_SOF: bytes([0x00]) + good[1:],
            Status.BAD_VERSION: good[:1] + bytes([9]) + good[2:],
            Status.BAD_CRC: good[:-1] + bytes([good[-1] ^ 0xFF]),
        }
        for status, frame in cases.items():
            with self.subTest(status=status.name):
                with self.assertRaises(ProtocolFault) as caught:
                    lsc1.decode_response(frame)
                self.assertIs(caught.exception.status, status)

    def test_response_decoder_rejects_short_frames(self) -> None:
        for length in range(RESPONSE_HEADER_BYTES + CRC_BYTES):
            with self.assertRaises(ProtocolFault) as caught:
                lsc1.decode_response(bytes(length))
            self.assertIs(caught.exception.status, Status.BAD_LENGTH)

    def test_reader_rejects_truncation_and_overrun(self) -> None:
        frame = simple_xor()
        with self.assertRaises(ProtocolFault) as short:
            lsc1.decode_request_payload(Opcode.XOR, frame.payload[:-1])
        self.assertIs(short.exception.status, Status.BAD_LENGTH)
        with self.assertRaises(ProtocolFault) as long:
            lsc1.decode_request_payload(Opcode.XOR, frame.payload + b"\x00")
        self.assertIs(long.exception.status, Status.BAD_LENGTH)

    def test_cell_presence_encoding_is_canonical(self) -> None:
        payload = bytearray(simple_xor().payload)
        presence = lsc1.TRANSACTION_PREAMBLE_BYTES + 12
        payload[presence] = 2
        with self.assertRaises(ProtocolFault) as bad_flag:
            lsc1.decode_request_payload(Opcode.XOR, bytes(payload))
        self.assertIs(bad_flag.exception.status, Status.BAD_CELL)

        payload = bytearray(simple_xor().payload)
        absent = lsc1.TRANSACTION_PREAMBLE_BYTES + 12 + 2 * lsc1.CELL_BYTES
        payload[absent + 1] = 0x01
        with self.assertRaises(ProtocolFault) as smuggled:
            lsc1.decode_request_payload(Opcode.XOR, bytes(payload))
        self.assertIs(smuggled.exception.status, Status.BAD_CELL)

    def test_cell_encoding_is_presence_byte_then_little_endian_value(self) -> None:
        cell = Cell(True, 0x0102030405060708090A0B0C0D0E0F10)
        encoded = cell.encode()
        self.assertEqual(len(encoded), lsc1.CELL_BYTES)
        self.assertEqual(encoded[0], 1)
        self.assertEqual(int.from_bytes(encoded[1:], "little"), cell.value)
        self.assertEqual(encoded[1], 0x10)


def all_request_frames() -> list[lsc1.RequestFrame]:
    """One well-formed frame per opcode, for codec-level sweeps."""
    cells = (Cell(True, 5), Cell(True, 6), ABSENT)
    return [
        lsc1.build_binary_op(
            Opcode.XOR, txn_id=1, pc=0, fp=8, profile=Profile.INTERPRETER_COMPAT,
            offsets=(1, 2, 3), cells=cells,
        ),
        lsc1.build_binary_op(
            Opcode.MUL_NATIVE, txn_id=1, pc=0, fp=8, profile=Profile.INTERPRETER_COMPAT,
            offsets=(1, 2, 3), cells=cells, proposed_inverse=ABSENT,
        ),
        lsc1.build_set_constant(
            txn_id=1, pc=0, fp=8, profile=Profile.INTERPRETER_COMPAT,
            offset=1, constant=0x1234, cell=ABSENT,
        ),
        *[
            lsc1.build_deref(
                opcode, txn_id=1, pc=0, fp=8, profile=Profile.INTERPRETER_COMPAT,
                alpha=0, beta=2, gamma=3, pointer=pointer_cell(40), base=40,
                target=ABSENT, local=Cell(True, 9),
            )
            for opcode in (Opcode.DEREF_CELL, Opcode.DEREF_PC, Opcode.DEREF_FP)
        ],
        lsc1.build_jump(
            txn_id=1, pc=0, fp=8, profile=Profile.INTERPRETER_COMPAT,
            offsets=(0, 1, 2), cells=(Cell(True, 0), Cell(True, 1), Cell(True, 1)),
            taken=False, dest_pc=0, dest_fp=0, proposed_inverse=ABSENT,
        ),
        lsc1.build_blake3(
            txn_id=1, pc=0, fp=8, profile=Profile.INTERPRETER_COMPAT,
            message_offsets=(0, 1, 2, 3), cv_offset=8, out_offset=10, metadata=0x40,
            message_cells=(Cell(True, 1), Cell(True, 2), Cell(True, 3), Cell(True, 4)),
            cv_cells=(Cell(True, 5), Cell(True, 6)), out_cells=(ABSENT, ABSENT),
        ),
        lsc1.build_negotiate(),
        lsc1.build_service_response(txn_id=1, service_id=1, digest=(7, 8)),
        lsc1.build_retire(txn_id=1, result_crc=0),
        lsc1.build_status_query(),
    ]


# --- Framing faults on the wire. --------------------------------------------


class FramingFaultTests(unittest.TestCase):
    def test_bad_start_of_frame_is_rejected_byte_for_byte(self) -> None:
        endpoint = Lsc1Endpoint()
        for byte in (0x00, 0x5A, 0xA0, 0xFF):
            with self.subTest(byte=byte):
                response, _ = lsc1.drive(endpoint, bytes([byte]))
                self.assertIs(lsc1.decode_response(response).status, Status.BAD_SOF)

    def test_unknown_version_faults_without_losing_frame_sync(self) -> None:
        endpoint = Lsc1Endpoint()
        for version in (0, 2, 0xFF):
            with self.subTest(version=version):
                frame = simple_xor()
                bad = lsc1.RequestFrame(frame.opcode, frame.payload, version=version)
                self.assertIs(exchange(endpoint, bad).status, Status.BAD_VERSION)
                self.assertIs(exchange(endpoint, simple_xor()).status, Status.OK)
                retire(endpoint)
                endpoint = Lsc1Endpoint()

    def test_unknown_opcode_faults(self) -> None:
        endpoint = Lsc1Endpoint()
        known = {int(opcode) for opcode in Opcode}
        for value in (0x00, 0x09, 0x14, 0xFF):
            self.assertNotIn(value, known)
            frame = lsc1.RequestFrame.__new__(lsc1.RequestFrame)
            object.__setattr__(frame, "opcode", value)
            object.__setattr__(frame, "payload", b"")
            object.__setattr__(frame, "flags", 0)
            object.__setattr__(frame, "version", PROTOCOL_VERSION)
            object.__setattr__(frame, "sof", SOF_REQUEST)
            with self.subTest(opcode=value):
                self.assertIs(exchange(endpoint, frame).status, Status.BAD_OPCODE)

    def test_nonzero_flags_are_reserved_and_rejected(self) -> None:
        endpoint = Lsc1Endpoint()
        frame = simple_xor()
        bad = lsc1.RequestFrame(frame.opcode, frame.payload, flags=0x01)
        self.assertIs(exchange(endpoint, bad).status, Status.BAD_FLAGS)

    def test_wrong_payload_length_for_opcode_faults(self) -> None:
        endpoint = Lsc1Endpoint()
        frame = simple_xor()
        short = lsc1.RequestFrame(frame.opcode, frame.payload[:-1])
        self.assertIs(exchange(endpoint, short).status, Status.BAD_LENGTH)
        long = lsc1.RequestFrame(frame.opcode, frame.payload + b"\x00")
        self.assertIs(exchange(endpoint, long).status, Status.BAD_LENGTH)

    def test_fixed_length_fault_echoes_decoded_txn_id_with_valid_crc(self) -> None:
        txn_id = 0x10203040
        frame = simple_xor(txn_id=txn_id)
        malformed = lsc1.RequestFrame(frame.opcode, frame.payload[:-1]).encode()

        encoded, _ = lsc1.drive(Lsc1Endpoint(), malformed)
        response = lsc1.decode_response(encoded)

        self.assertIs(response.status, Status.BAD_LENGTH)
        self.assertEqual(response.payload, txn_id.to_bytes(4, "little") + b"\x02")
        self.assertEqual(
            int.from_bytes(encoded[-CRC_BYTES:], "little"),
            ref_crc32(encoded[:-CRC_BYTES]),
        )

    def test_fixed_length_fault_only_echoes_transaction_bearing_opcodes(self) -> None:
        txn_id = 0x10203040
        cases = (
            (lsc1.RequestFrame(Opcode.NEGOTIATE, txn_id.to_bytes(4, "little")), 0),
            (lsc1.RequestFrame(Opcode.STATUS_QUERY, txn_id.to_bytes(4, "little")), 0),
            (lsc1.RequestFrame(Opcode.RETIRE, txn_id.to_bytes(4, "little")), txn_id),
        )
        for frame, expected_txn_id in cases:
            with self.subTest(opcode=frame.opcode):
                response = exchange(Lsc1Endpoint(), frame)
                self.assertIs(response.status, Status.BAD_LENGTH)
                self.assertEqual(response.payload, expected_txn_id.to_bytes(4, "little") + b"\x02")

    def test_oversized_declared_length_faults_at_the_header(self) -> None:
        endpoint = Lsc1Endpoint()
        header = bytes([SOF_REQUEST, PROTOCOL_VERSION, int(Opcode.XOR), 0])
        header += (MAX_PAYLOAD_BYTES + 1).to_bytes(2, "little")
        response, _ = lsc1.drive(endpoint, header)
        self.assertIs(lsc1.decode_response(response).status, Status.BAD_LENGTH)
        self.assertIs(exchange(endpoint, simple_xor()).status, Status.OK)

    def test_every_single_bit_flip_outside_the_length_field_is_caught(self) -> None:
        frame = simple_xor().encode()
        length_field = range(4, 6)
        for index in range(1, len(frame)):
            if index in length_field:
                continue
            for bit in range(8):
                corrupted = bytearray(frame)
                corrupted[index] ^= 1 << bit
                with self.subTest(index=index, bit=bit):
                    endpoint = Lsc1Endpoint()
                    response, _ = lsc1.drive(endpoint, bytes(corrupted))
                    status = lsc1.decode_response(response).status
                    self.assertGreaterEqual(int(status), 0x80)
                    self.assertIsNone(endpoint.staged)
                    self.assertEqual(endpoint.retire_seq, 0)

    def test_a_corrupted_length_field_desynchronizes_until_the_host_aborts(self) -> None:
        # The length field is what tells the endpoint where the frame ends, so a
        # flip inside it is the one corruption CRC cannot catch in time: the
        # endpoint keeps waiting for bytes the host never promised.  Recovery is
        # the host's timeout plus ABORT, not an in-band resynchronization.
        frame = bytearray(simple_xor().encode())
        frame[4] ^= 0x80  # 77 -> 205 payload bytes, still within the declared cap
        endpoint = Lsc1Endpoint()
        for byte in frame:
            endpoint.step(rx_data=byte, rx_valid=True)
        self.assertFalse(endpoint.pins().tx_valid)
        self.assertTrue(endpoint.pins().busy)
        self.assertIsNone(endpoint.staged)
        endpoint.step(abort=True)
        self.assertIs(exchange(endpoint, simple_xor()).status, Status.OK)

    def test_a_length_field_beyond_the_cap_faults_without_waiting(self) -> None:
        frame = bytearray(simple_xor().encode())
        frame[5] ^= 0x01  # 77 -> 333 payload bytes, past MAX_PAYLOAD_BYTES
        endpoint = Lsc1Endpoint()
        response, _ = lsc1.drive(endpoint, bytes(frame[:REQUEST_HEADER_BYTES]))
        self.assertIs(lsc1.decode_response(response).status, Status.BAD_LENGTH)
        self.assertIs(exchange(endpoint, simple_xor()).status, Status.OK)

    def test_a_shortened_length_field_is_caught_by_the_crc(self) -> None:
        frame = bytearray(simple_xor().encode())
        frame[4] = 0x0D  # 77 -> 13 payload bytes
        endpoint = Lsc1Endpoint()
        consumed = REQUEST_HEADER_BYTES + 13 + CRC_BYTES
        response, _ = lsc1.drive(endpoint, bytes(frame[:consumed]))
        self.assertIs(lsc1.decode_response(response).status, Status.BAD_CRC)
        self.assertIsNone(endpoint.staged)
        # The bytes the short frame left behind are not a frame; the endpoint
        # rejects them rather than silently absorbing them.
        endpoint.step(abort=True)
        self.assertIs(exchange(endpoint, simple_xor()).status, Status.OK)

    def test_a_faulted_frame_leaves_no_staged_transaction(self) -> None:
        endpoint = Lsc1Endpoint()
        frame = simple_xor()
        broken = frame.encode()[:-1] + bytes([frame.encode()[-1] ^ 0xFF])
        lsc1.drive(endpoint, broken)
        self.assertIs(endpoint.state, TxnState.IDLE)
        self.assertIsNone(endpoint.staged)
        self.assertEqual(endpoint.retire_seq, 0)


# --- Ready/valid transport. -------------------------------------------------


class TransportTests(unittest.TestCase):
    def test_response_bytes_are_identical_under_arbitrary_stall_patterns(self) -> None:
        baseline, _ = lsc1.drive(Lsc1Endpoint(), simple_xor().encode())
        rng = random.Random(SEED + 5)
        for _ in range(24):
            rx_gaps = [rng.randrange(0, 4) for _ in range(rng.randrange(1, 6))]
            tx_gaps = [rng.randrange(0, 4) for _ in range(rng.randrange(1, 6))]
            with self.subTest(rx_gaps=tuple(rx_gaps), tx_gaps=tuple(tx_gaps)):
                stalled, _ = lsc1.drive(
                    Lsc1Endpoint(), simple_xor().encode(), rx_gaps=rx_gaps, tx_gaps=tx_gaps
                )
                self.assertEqual(stalled, baseline)

    def test_stalls_only_ever_cost_cycles(self) -> None:
        _, fast = lsc1.drive(Lsc1Endpoint(), simple_xor().encode())
        _, slow = lsc1.drive(
            Lsc1Endpoint(), simple_xor().encode(), rx_gaps=[3], tx_gaps=[3]
        )
        self.assertGreater(slow, fast)

    def test_backpressure_holds_the_same_byte_and_refuses_input(self) -> None:
        endpoint = Lsc1Endpoint()
        frame = simple_xor().encode()
        for byte in frame:
            endpoint.step(rx_data=byte, rx_valid=True, tx_ready=False)
        first = endpoint.step(rx_data=0xA1, rx_valid=True, tx_ready=False)
        second = endpoint.step(rx_data=0xA1, rx_valid=True, tx_ready=False)
        self.assertTrue(first.pins.tx_valid)
        self.assertFalse(first.pins.rx_ready)
        self.assertFalse(first.rx_committed)
        self.assertEqual(first.pins.tx_data, SOF_RESPONSE)
        self.assertEqual(second.pins.tx_data, SOF_RESPONSE)
        self.assertFalse(second.tx_committed)

    def test_no_byte_is_accepted_while_a_response_is_outstanding(self) -> None:
        endpoint = Lsc1Endpoint()
        for byte in simple_xor().encode():
            endpoint.step(rx_data=byte, rx_valid=True)
        accepted = 0
        for _ in range(8):
            record = endpoint.step(rx_data=SOF_REQUEST, rx_valid=True, tx_ready=False)
            accepted += int(record.rx_committed)
        self.assertEqual(accepted, 0)

    def test_deasserted_valid_commits_nothing(self) -> None:
        endpoint = Lsc1Endpoint()
        for _ in range(4):
            record = endpoint.step(rx_data=SOF_REQUEST, rx_valid=False)
            self.assertFalse(record.rx_committed)
        self.assertIs(endpoint.state, TxnState.IDLE)
        self.assertIs(exchange(endpoint, simple_xor()).status, Status.OK)

    def test_done_pulse_is_one_cycle_wide_and_only_on_retirement(self) -> None:
        endpoint = Lsc1Endpoint()
        exchange(endpoint, simple_xor())
        staged = endpoint.staged
        assert staged is not None
        frame = lsc1.build_retire(
            txn_id=staged.txn_id, result_crc=staged.result_crc
        ).encode()
        for byte in frame:
            record = endpoint.step(rx_data=byte, rx_valid=True)
            self.assertFalse(record.pins.done_pulse)
        self.assertTrue(endpoint.pins().done_pulse)
        endpoint.step(tx_ready=True)
        self.assertFalse(endpoint.pins().done_pulse)

    def test_fault_pin_tracks_the_last_status(self) -> None:
        endpoint = Lsc1Endpoint()
        self.assertFalse(endpoint.pins().fault)
        lsc1.drive(endpoint, bytes([0x00]))
        self.assertTrue(endpoint.pins().fault)
        exchange(endpoint, lsc1.build_status_query())
        self.assertFalse(endpoint.pins().fault)


# --- Abort and reset. -------------------------------------------------------


class AbortResetTests(unittest.TestCase):
    def test_abort_at_every_byte_boundary_leaves_no_state_effect(self) -> None:
        frame = simple_xor().encode()
        for boundary in range(len(frame) + 1):
            with self.subTest(boundary=boundary):
                endpoint = Lsc1Endpoint()
                for byte in frame[:boundary]:
                    endpoint.step(rx_data=byte, rx_valid=True)
                endpoint.step(abort=True)
                self.assertIs(endpoint.state, TxnState.IDLE)
                self.assertIsNone(endpoint.staged)
                self.assertEqual(endpoint.committed_pc, 0)
                self.assertEqual(endpoint.committed_fp, 0)
                self.assertFalse(endpoint.state_valid)
                self.assertEqual(endpoint.retire_seq, 0)
                self.assertIs(endpoint.last_status, Status.ABORTED)
                self.assertTrue(endpoint.pins().fault)

    def test_the_lane_is_reusable_after_an_abort_at_any_boundary(self) -> None:
        frame = simple_xor().encode()
        for boundary in range(len(frame) + 1):
            with self.subTest(boundary=boundary):
                endpoint = Lsc1Endpoint()
                for byte in frame[:boundary]:
                    endpoint.step(rx_data=byte, rx_valid=True)
                endpoint.step(abort=True)
                for _ in range(4):
                    endpoint.step(tx_ready=True)
                self.assertIs(exchange(endpoint, simple_xor()).status, Status.OK)
                self.assertIs(retire(endpoint).status, Status.RETIRED)
                self.assertEqual(endpoint.retire_seq, 1)

    def test_abort_discards_a_staged_but_unretired_transaction(self) -> None:
        endpoint = Lsc1Endpoint()
        exchange(endpoint, simple_xor())
        self.assertIs(endpoint.state, TxnState.RESULT_PENDING)
        endpoint.step(abort=True)
        self.assertIsNone(endpoint.staged)
        self.assertEqual(endpoint.retire_seq, 0)
        self.assertFalse(endpoint.state_valid)

    def test_abort_takes_priority_over_a_same_edge_transfer(self) -> None:
        endpoint = Lsc1Endpoint()
        exchange(endpoint, simple_xor())
        for byte in lsc1.build_retire(txn_id=1, result_crc=0).encode()[:3]:
            endpoint.step(rx_data=byte, rx_valid=True)
        edge = endpoint.step(rx_data=SOF_REQUEST, rx_valid=True, tx_ready=True, abort=True)
        self.assertFalse(edge.rx_committed)
        self.assertFalse(edge.tx_committed)

    def test_reset_clears_committed_state_and_the_fault_pin(self) -> None:
        endpoint = Lsc1Endpoint()
        exchange(endpoint, simple_xor())
        retire(endpoint)
        self.assertEqual(endpoint.retire_seq, 1)
        endpoint.step(reset_n=False)
        self.assertEqual(endpoint.retire_seq, 0)
        self.assertEqual(endpoint.committed_pc, 0)
        self.assertFalse(endpoint.state_valid)
        self.assertFalse(endpoint.pins().fault)
        self.assertIs(endpoint.profile, lsc1.DEFAULT_PROFILE)

    def test_reset_at_every_byte_boundary_returns_the_lane_to_idle(self) -> None:
        frame = simple_xor().encode()
        for boundary in range(len(frame) + 1):
            with self.subTest(boundary=boundary):
                endpoint = Lsc1Endpoint()
                for byte in frame[:boundary]:
                    endpoint.step(rx_data=byte, rx_valid=True)
                endpoint.step(reset_n=False)
                idle = endpoint.pins()
                self.assertTrue(idle.rx_ready)
                self.assertFalse(idle.busy)
                self.assertFalse(idle.fault)

    def test_reset_takes_priority_over_abort(self) -> None:
        endpoint = Lsc1Endpoint()
        endpoint.step(rx_data=SOF_REQUEST, rx_valid=True, abort=True, reset_n=False)
        self.assertIs(endpoint.last_status, Status.OK)
        self.assertEqual(endpoint.abort_count, 0)


# --- Profile negotiation. ---------------------------------------------------


class ProfileTests(unittest.TestCase):
    def test_default_profile_is_interpreter_compatible(self) -> None:
        self.assertIs(Lsc1Endpoint().profile, Profile.INTERPRETER_COMPAT)

    def test_negotiate_reports_the_device_envelope(self) -> None:
        endpoint = Lsc1Endpoint()
        reply = exchange(endpoint, lsc1.build_negotiate(profile=Profile.FORWARD_ONLY))
        self.assertIs(reply.status, Status.OK)
        reader = lsc1._Reader(reply.payload)
        self.assertEqual(reader.u8(), PROTOCOL_VERSION)
        self.assertEqual(reader.u8(), int(Profile.FORWARD_ONLY))
        self.assertEqual(reader.u16(), MAX_PAYLOAD_BYTES)
        self.assertEqual(reader.u8(), lsc1.INDEX_BITS)
        self.assertEqual(reader.u8(), 0)
        self.assertEqual(reader.u32(), lsc1.DEVICE_FEATURES)
        self.assertEqual(reader.u32(), lsc1.DEVICE_ID)
        reader.done()
        self.assertIs(endpoint.profile, Profile.FORWARD_ONLY)

    def test_negotiate_rejects_a_version_window_that_excludes_v1(self) -> None:
        endpoint = Lsc1Endpoint()
        for low, high in ((2, 3), (0, 0), (5, 4)):
            with self.subTest(window=(low, high)):
                reply = exchange(
                    endpoint, lsc1.build_negotiate(version_min=low, version_max=high)
                )
                self.assertIs(reply.status, Status.BAD_VERSION)
        self.assertIs(endpoint.profile, lsc1.DEFAULT_PROFILE)

    def test_negotiate_rejects_an_unknown_profile(self) -> None:
        endpoint = Lsc1Endpoint()
        payload = bytes([PROTOCOL_VERSION, PROTOCOL_VERSION, 0x77]) + (0).to_bytes(4, "little")
        reply = exchange(endpoint, lsc1.RequestFrame(Opcode.NEGOTIATE, payload))
        self.assertIs(reply.status, Status.BAD_PROFILE)

    def test_a_request_naming_the_other_profile_is_rejected(self) -> None:
        endpoint = negotiated(Profile.FORWARD_ONLY)
        reply = exchange(endpoint, simple_xor())
        self.assertIs(reply.status, Status.BAD_PROFILE)
        self.assertIsNone(endpoint.staged)

    def test_negotiation_is_refused_mid_transaction(self) -> None:
        endpoint = Lsc1Endpoint()
        exchange(endpoint, simple_xor())
        reply = exchange(endpoint, lsc1.build_negotiate(profile=Profile.FORWARD_ONLY))
        self.assertIs(reply.status, Status.BAD_STATE)
        self.assertIs(endpoint.profile, Profile.INTERPRETER_COMPAT)


# --- Scalar semantics: XOR and MUL. -----------------------------------------


class BinaryOpTests(unittest.TestCase):
    def forward(self, opcode: Opcode, left: int, right: int) -> lsc1.StagedTransaction:
        endpoint = Lsc1Endpoint()
        frame = lsc1.build_binary_op(
            opcode, txn_id=1, pc=3, fp=64, profile=Profile.INTERPRETER_COMPAT,
            offsets=(1, 2, 3), cells=(Cell(True, left), Cell(True, right), ABSENT),
        )
        self.assertIs(exchange(endpoint, frame).status, Status.OK)
        staged = endpoint.staged
        assert staged is not None
        return staged

    def test_xor_forward_writes_the_sum(self) -> None:
        rng = random.Random(SEED + 6)
        for _ in range(16):
            left, right = rng.getrandbits(128), rng.getrandbits(128)
            staged = self.forward(Opcode.XOR, left, right)
            self.assertEqual(staged.writes, [lsc1.Write(67, left ^ right)])
            self.assertEqual((staged.next_pc, staged.next_fp), (4, 64))
            self.assertEqual(staged.accesses, [65, 66, 67])

    def test_mul_forward_writes_the_field_product(self) -> None:
        rng = random.Random(SEED + 7)
        for _ in range(8):
            left, right = rng.getrandbits(128), rng.getrandbits(128)
            staged = self.forward(Opcode.MUL_NATIVE, left, right)
            self.assertEqual(staged.writes, [lsc1.Write(67, ref_mul(left, right))])

    def test_xor_back_solves_the_absent_operand_in_interpreter_profile(self) -> None:
        for absent_index in (0, 1):
            with self.subTest(absent=absent_index):
                endpoint = Lsc1Endpoint()
                known, result = 0x1234, 0xABCD
                cells = [Cell(True, known), Cell(True, known), Cell(True, result)]
                cells[absent_index] = ABSENT
                frame = lsc1.build_binary_op(
                    Opcode.XOR, txn_id=1, pc=0, fp=64,
                    profile=Profile.INTERPRETER_COMPAT,
                    offsets=(1, 2, 3), cells=tuple(cells),
                )
                self.assertIs(exchange(endpoint, frame).status, Status.OK)
                staged = endpoint.staged
                assert staged is not None
                self.assertEqual(
                    staged.writes, [lsc1.Write(65 + absent_index, known ^ result)]
                )

    def test_mul_back_solve_multiplies_by_the_verified_host_inverse(self) -> None:
        known, result = 0x9, 0x33
        inverse = pow_inverse(known)
        endpoint = Lsc1Endpoint()
        frame = lsc1.build_binary_op(
            Opcode.MUL_NATIVE, txn_id=1, pc=0, fp=64,
            profile=Profile.INTERPRETER_COMPAT,
            offsets=(1, 2, 3),
            cells=(ABSENT, Cell(True, known), Cell(True, result)),
            proposed_inverse=Cell(True, inverse),
        )
        self.assertIs(exchange(endpoint, frame).status, Status.OK)
        staged = endpoint.staged
        assert staged is not None
        self.assertEqual(staged.writes, [lsc1.Write(65, ref_mul(result, inverse))])
        self.assertEqual(ref_mul(staged.writes[0].value, known), result)

    def test_mul_back_solve_rejects_a_wrong_inverse(self) -> None:
        for proposal in (ABSENT, Cell(True, 0), Cell(True, 1), Cell(True, 0xDEAD)):
            with self.subTest(proposal=proposal):
                endpoint = Lsc1Endpoint()
                frame = lsc1.build_binary_op(
                    Opcode.MUL_NATIVE, txn_id=1, pc=0, fp=64,
                    profile=Profile.INTERPRETER_COMPAT,
                    offsets=(1, 2, 3),
                    cells=(ABSENT, Cell(True, 9), Cell(True, 0x33)),
                    proposed_inverse=proposal,
                )
                self.assertIs(exchange(endpoint, frame).status, Status.BAD_INVERSE)
                self.assertIsNone(endpoint.staged)

    def test_mul_back_solve_through_zero_is_refused(self) -> None:
        endpoint = Lsc1Endpoint()
        frame = lsc1.build_binary_op(
            Opcode.MUL_NATIVE, txn_id=1, pc=0, fp=64,
            profile=Profile.INTERPRETER_COMPAT,
            offsets=(1, 2, 3),
            cells=(ABSENT, Cell(True, 0), Cell(True, 0x33)),
            proposed_inverse=Cell(True, 1),
        )
        self.assertIs(exchange(endpoint, frame).status, Status.MUL_BACKSOLVE_ZERO)

    def test_forward_only_profile_refuses_any_absent_operand(self) -> None:
        for cells in (
            (ABSENT, Cell(True, 2), Cell(True, 3)),
            (Cell(True, 1), ABSENT, Cell(True, 3)),
            (ABSENT, ABSENT, Cell(True, 3)),
        ):
            with self.subTest(cells=cells):
                endpoint = negotiated(Profile.FORWARD_ONLY)
                frame = lsc1.build_binary_op(
                    Opcode.XOR, txn_id=1, pc=0, fp=64, profile=Profile.FORWARD_ONLY,
                    offsets=(1, 2, 3), cells=cells,
                )
                reply = exchange(endpoint, frame)
                self.assertIs(reply.status, Status.UNSUPPORTED_IN_PROFILE)
                self.assertIsNone(endpoint.staged)

    def test_forward_only_profile_accepts_a_fully_supplied_operand_pair(self) -> None:
        endpoint = negotiated(Profile.FORWARD_ONLY)
        frame = lsc1.build_binary_op(
            Opcode.XOR, txn_id=1, pc=0, fp=64, profile=Profile.FORWARD_ONLY,
            offsets=(1, 2, 3), cells=(Cell(True, 6), Cell(True, 3), ABSENT),
        )
        self.assertIs(exchange(endpoint, frame).status, Status.OK)
        staged = endpoint.staged
        assert staged is not None
        self.assertEqual(staged.writes, [lsc1.Write(67, 5)])

    def test_writing_a_conflicting_result_is_a_write_conflict(self) -> None:
        endpoint = Lsc1Endpoint()
        frame = lsc1.build_binary_op(
            Opcode.XOR, txn_id=1, pc=0, fp=64, profile=Profile.INTERPRETER_COMPAT,
            offsets=(1, 2, 3),
            cells=(Cell(True, 1), Cell(True, 2), Cell(True, 0xFF)),
        )
        self.assertIs(exchange(endpoint, frame).status, Status.WRITE_CONFLICT)
        self.assertIsNone(endpoint.staged)

    def test_an_already_consistent_result_produces_no_write(self) -> None:
        endpoint = Lsc1Endpoint()
        frame = lsc1.build_binary_op(
            Opcode.XOR, txn_id=1, pc=0, fp=64, profile=Profile.INTERPRETER_COMPAT,
            offsets=(1, 2, 3),
            cells=(Cell(True, 1), Cell(True, 2), Cell(True, 3)),
        )
        self.assertIs(exchange(endpoint, frame).status, Status.OK)
        staged = endpoint.staged
        assert staged is not None
        self.assertEqual(staged.writes, [])

    def test_aliased_operands_must_agree(self) -> None:
        endpoint = Lsc1Endpoint()
        frame = lsc1.build_binary_op(
            Opcode.XOR, txn_id=1, pc=0, fp=64, profile=Profile.INTERPRETER_COMPAT,
            offsets=(1, 1, 3),
            cells=(Cell(True, 1), Cell(True, 2), ABSENT),
        )
        self.assertIs(exchange(endpoint, frame).status, Status.ALIAS_INCONSISTENT)

    def test_aliased_operands_that_agree_are_accepted(self) -> None:
        endpoint = Lsc1Endpoint()
        frame = lsc1.build_binary_op(
            Opcode.XOR, txn_id=1, pc=0, fp=64, profile=Profile.INTERPRETER_COMPAT,
            offsets=(1, 1, 3),
            cells=(Cell(True, 7), Cell(True, 7), ABSENT),
        )
        self.assertIs(exchange(endpoint, frame).status, Status.OK)
        staged = endpoint.staged
        assert staged is not None
        self.assertEqual(staged.writes, [lsc1.Write(67, 0)])

    def test_u32_overflow_in_operand_addressing_faults(self) -> None:
        endpoint = Lsc1Endpoint()
        frame = lsc1.build_binary_op(
            Opcode.XOR, txn_id=1, pc=0, fp=2, profile=Profile.INTERPRETER_COMPAT,
            offsets=(U32_MAX, 2, 3), cells=(Cell(True, 1), Cell(True, 2), ABSENT),
        )
        self.assertIs(exchange(endpoint, frame).status, Status.U32_OVERFLOW)
        self.assertIsNone(endpoint.staged)


def pow_inverse(value: int) -> int:
    """Field inverse by Fermat exponentiation, using the reference product."""
    result = 1
    base = value
    exponent = (1 << 128) - 2
    while exponent:
        if exponent & 1:
            result = ref_mul(result, base)
        base = ref_mul(base, base)
        exponent >>= 1
    return result


# --- Scalar semantics: SET, DEREF, JUMP. ------------------------------------


class SetConstantTests(unittest.TestCase):
    def test_set_writes_the_constant_and_advances_pc(self) -> None:
        endpoint = Lsc1Endpoint()
        frame = lsc1.build_set_constant(
            txn_id=1, pc=9, fp=32, profile=Profile.INTERPRETER_COMPAT,
            offset=4, constant=0xFEEDFACE, cell=ABSENT,
        )
        self.assertIs(exchange(endpoint, frame).status, Status.OK)
        staged = endpoint.staged
        assert staged is not None
        self.assertEqual(staged.writes, [lsc1.Write(36, 0xFEEDFACE)])
        self.assertEqual(staged.accesses, [36])
        self.assertEqual((staged.next_pc, staged.next_fp), (10, 32))

    def test_set_over_a_differing_written_cell_is_a_write_conflict(self) -> None:
        endpoint = Lsc1Endpoint()
        frame = lsc1.build_set_constant(
            txn_id=1, pc=0, fp=32, profile=Profile.INTERPRETER_COMPAT,
            offset=4, constant=7, cell=Cell(True, 8),
        )
        self.assertIs(exchange(endpoint, frame).status, Status.WRITE_CONFLICT)


class DerefTests(unittest.TestCase):
    BASE = 40

    def deref(
        self,
        opcode: Opcode,
        *,
        profile: Profile,
        target: Cell,
        local: Cell,
        pointer: Cell | None = None,
        base: int | None = None,
        pc: int = 5,
        fp: int = 64,
    ) -> tuple[Lsc1Endpoint, lsc1.ResponseFrame]:
        endpoint = negotiated(profile)
        frame = lsc1.build_deref(
            opcode, txn_id=1, pc=pc, fp=fp, profile=profile,
            alpha=0, beta=2, gamma=3,
            pointer=pointer if pointer is not None else pointer_cell(self.BASE),
            base=self.BASE if base is None else base,
            target=target, local=local,
        )
        return endpoint, exchange(endpoint, frame)

    def test_cell_quadrants_in_interpreter_profile(self) -> None:
        value = 0x99
        expectations = {
            (True, True): ([], []),
            (True, False): ([lsc1.Write(67, value)], []),
            (False, True): ([lsc1.Write(42, value)], []),
            (False, False): ([], [lsc1.DeferredEquality(42, 67)]),
        }
        for (has_target, has_local), (writes, deferred) in expectations.items():
            with self.subTest(target=has_target, local=has_local):
                endpoint, reply = self.deref(
                    Opcode.DEREF_CELL,
                    profile=Profile.INTERPRETER_COMPAT,
                    target=Cell(True, value) if has_target else ABSENT,
                    local=Cell(True, value) if has_local else ABSENT,
                )
                self.assertIs(reply.status, Status.OK)
                staged = endpoint.staged
                assert staged is not None
                self.assertEqual(staged.writes, writes)
                self.assertEqual(staged.deferred, deferred)
                self.assertEqual(staged.accesses, [64, 42, 67])

    def test_cell_quadrants_in_forward_only_profile(self) -> None:
        value = 0x99
        expectations = {
            (True, True): (Status.OK, []),
            (True, False): (Status.UNSUPPORTED_IN_PROFILE, None),
            (False, True): (Status.OK, [lsc1.Write(42, value)]),
            (False, False): (Status.UNSUPPORTED_IN_PROFILE, None),
        }
        for (has_target, has_local), (status, writes) in expectations.items():
            with self.subTest(target=has_target, local=has_local):
                endpoint, reply = self.deref(
                    Opcode.DEREF_CELL,
                    profile=Profile.FORWARD_ONLY,
                    target=Cell(True, value) if has_target else ABSENT,
                    local=Cell(True, value) if has_local else ABSENT,
                )
                self.assertIs(reply.status, status)
                if writes is None:
                    self.assertIsNone(endpoint.staged)
                else:
                    staged = endpoint.staged
                    assert staged is not None
                    self.assertEqual(staged.writes, writes)

    def test_both_sides_written_but_unequal_is_a_mismatch(self) -> None:
        for profile in (Profile.INTERPRETER_COMPAT, Profile.FORWARD_ONLY):
            with self.subTest(profile=profile.name):
                endpoint, reply = self.deref(
                    Opcode.DEREF_CELL, profile=profile,
                    target=Cell(True, 1), local=Cell(True, 2),
                )
                self.assertIs(reply.status, Status.DEREF_MISMATCH)
                self.assertIsNone(endpoint.staged)

    def test_deferred_equality_is_reported_never_resolved_on_chip(self) -> None:
        endpoint, reply = self.deref(
            Opcode.DEREF_CELL, profile=Profile.INTERPRETER_COMPAT,
            target=ABSENT, local=ABSENT,
        )
        self.assertIs(reply.status, Status.OK)
        staged = endpoint.staged
        assert staged is not None
        self.assertEqual(len(staged.deferred), 1)
        self.assertEqual(staged.writes, [])

    def test_pc_mode_stores_the_encoding_of_pc_plus_two(self) -> None:
        for pc in (0, 1, 5, 100, 4095):
            with self.subTest(pc=pc):
                endpoint, reply = self.deref(
                    Opcode.DEREF_PC, profile=Profile.INTERPRETER_COMPAT,
                    target=ABSENT, local=ABSENT, pc=pc,
                )
                self.assertIs(reply.status, Status.OK)
                staged = endpoint.staged
                assert staged is not None
                self.assertEqual(staged.writes, [lsc1.Write(42, ref_encode(pc + 2))])

    def test_pc_mode_does_not_store_the_encoding_of_pc_plus_gamma(self) -> None:
        # isa.rs still documents "pc+gamma"; execute.rs and doc.tex agree on
        # pc+2, and gamma = 3 here, so the two readings are distinguishable.
        endpoint, reply = self.deref(
            Opcode.DEREF_PC, profile=Profile.INTERPRETER_COMPAT,
            target=ABSENT, local=ABSENT, pc=5,
        )
        self.assertIs(reply.status, Status.OK)
        staged = endpoint.staged
        assert staged is not None
        self.assertNotEqual(staged.writes[0].value, ref_encode(5 + 3))
        self.assertEqual(staged.writes[0].value, ref_encode(5 + 2))

    def test_fp_mode_stores_the_encoding_of_fp(self) -> None:
        for fp in (0, 1, 64, 4096):
            with self.subTest(fp=fp):
                endpoint, reply = self.deref(
                    Opcode.DEREF_FP, profile=Profile.INTERPRETER_COMPAT,
                    target=ABSENT, local=ABSENT, fp=fp,
                )
                self.assertIs(reply.status, Status.OK)
                staged = endpoint.staged
                assert staged is not None
                self.assertEqual(staged.writes, [lsc1.Write(42, ref_encode(fp))])

    def test_a_pointer_that_is_not_the_claimed_g_power_is_rejected(self) -> None:
        for pointer in (Cell(True, 0), Cell(True, 1), Cell(True, 0xDEAD), ABSENT):
            with self.subTest(pointer=pointer):
                endpoint, reply = self.deref(
                    Opcode.DEREF_CELL, profile=Profile.INTERPRETER_COMPAT,
                    target=ABSENT, local=Cell(True, 1), pointer=pointer,
                )
                self.assertIs(reply.status, Status.BAD_POINTER)
                self.assertIsNone(endpoint.staged)

    def test_a_base_index_beyond_the_verifiable_range_is_rejected(self) -> None:
        endpoint, reply = self.deref(
            Opcode.DEREF_CELL, profile=Profile.INTERPRETER_COMPAT,
            target=ABSENT, local=Cell(True, 1),
            pointer=pointer_cell(3), base=lsc1.INDEX_LIMIT,
        )
        self.assertIs(reply.status, Status.INDEX_RANGE)

    def test_pointer_verification_accepts_every_small_g_power(self) -> None:
        rng = random.Random(SEED + 8)
        for _ in range(12):
            base = rng.randrange(0, 1 << 12)
            with self.subTest(base=base):
                endpoint = Lsc1Endpoint()
                frame = lsc1.build_deref(
                    Opcode.DEREF_FP, txn_id=1, pc=0, fp=64,
                    profile=Profile.INTERPRETER_COMPAT,
                    alpha=0, beta=2, gamma=3,
                    pointer=Cell(True, ref_encode(base)), base=base,
                    target=ABSENT, local=ABSENT,
                )
                self.assertIs(exchange(endpoint, frame).status, Status.OK)


class JumpTests(unittest.TestCase):
    def jump(
        self, *, condition: Cell, taken: bool, dest_pc: int, dest_fp: int,
        inverse: Cell, destination: Cell | None = None, new_frame: Cell | None = None,
    ) -> tuple[Lsc1Endpoint, lsc1.ResponseFrame]:
        endpoint = Lsc1Endpoint()
        frame = lsc1.build_jump(
            txn_id=1, pc=5, fp=64, profile=Profile.INTERPRETER_COMPAT,
            offsets=(0, 1, 2),
            cells=(
                condition,
                destination if destination is not None else pointer_cell(dest_pc),
                new_frame if new_frame is not None else pointer_cell(dest_fp),
            ),
            taken=taken, dest_pc=dest_pc, dest_fp=dest_fp, proposed_inverse=inverse,
        )
        return endpoint, exchange(endpoint, frame)

    def test_taken_branch_moves_pc_and_fp_to_the_verified_targets(self) -> None:
        condition = 0x2B
        endpoint, reply = self.jump(
            condition=Cell(True, condition), taken=True, dest_pc=11, dest_fp=200,
            inverse=Cell(True, pow_inverse(condition)),
        )
        self.assertIs(reply.status, Status.OK)
        staged = endpoint.staged
        assert staged is not None
        self.assertEqual((staged.next_pc, staged.next_fp), (11, 200))
        self.assertEqual(staged.writes, [])

    def test_not_taken_branch_advances_pc_and_keeps_fp(self) -> None:
        endpoint, reply = self.jump(
            condition=Cell(True, 0), taken=False, dest_pc=0, dest_fp=0,
            inverse=Cell(True, 0), destination=Cell(True, 1), new_frame=Cell(True, 1),
        )
        self.assertIs(reply.status, Status.OK)
        staged = endpoint.staged
        assert staged is not None
        self.assertEqual((staged.next_pc, staged.next_fp), (6, 64))

    def test_all_three_operands_are_read_on_both_branch_outcomes(self) -> None:
        taken_endpoint, _ = self.jump(
            condition=Cell(True, 3), taken=True, dest_pc=11, dest_fp=200,
            inverse=Cell(True, pow_inverse(3)),
        )
        not_taken_endpoint, _ = self.jump(
            condition=Cell(True, 0), taken=False, dest_pc=0, dest_fp=0,
            inverse=Cell(True, 0), destination=Cell(True, 1), new_frame=Cell(True, 1),
        )
        for endpoint in (taken_endpoint, not_taken_endpoint):
            staged = endpoint.staged
            assert staged is not None
            self.assertEqual(staged.accesses, [64, 65, 66])

    def test_a_misdeclared_branch_outcome_is_rejected(self) -> None:
        _, wrongly_taken = self.jump(
            condition=Cell(True, 0), taken=True, dest_pc=11, dest_fp=200,
            inverse=Cell(True, 1),
        )
        self.assertIs(wrongly_taken.status, Status.BAD_BRANCH_PROPOSAL)
        _, wrongly_not_taken = self.jump(
            condition=Cell(True, 7), taken=False, dest_pc=0, dest_fp=0,
            inverse=Cell(True, 0), destination=Cell(True, 1), new_frame=Cell(True, 1),
        )
        self.assertIs(wrongly_not_taken.status, Status.BAD_BRANCH_PROPOSAL)

    def test_a_taken_branch_needs_a_verified_condition_inverse(self) -> None:
        for inverse in (ABSENT, Cell(True, 0), Cell(True, 1), Cell(True, 0xF00D)):
            with self.subTest(inverse=inverse):
                _, reply = self.jump(
                    condition=Cell(True, 0x2B), taken=True, dest_pc=11, dest_fp=200,
                    inverse=inverse,
                )
                self.assertIs(reply.status, Status.BAD_INVERSE)

    def test_a_not_taken_branch_pins_the_witness_to_zero(self) -> None:
        _, reply = self.jump(
            condition=Cell(True, 0), taken=False, dest_pc=0, dest_fp=0,
            inverse=Cell(True, 5), destination=Cell(True, 1), new_frame=Cell(True, 1),
        )
        self.assertIs(reply.status, Status.BAD_INVERSE)

    def test_a_not_taken_branch_must_not_propose_targets(self) -> None:
        _, reply = self.jump(
            condition=Cell(True, 0), taken=False, dest_pc=9, dest_fp=0,
            inverse=Cell(True, 0), destination=Cell(True, 1), new_frame=Cell(True, 1),
        )
        self.assertIs(reply.status, Status.BAD_BRANCH_PROPOSAL)

    def test_a_taken_branch_target_must_decode_to_the_operand(self) -> None:
        _, bad_pc = self.jump(
            condition=Cell(True, 3), taken=True, dest_pc=11, dest_fp=200,
            inverse=Cell(True, pow_inverse(3)), destination=Cell(True, 0xBAD),
        )
        self.assertIs(bad_pc.status, Status.BAD_POINTER)
        _, bad_fp = self.jump(
            condition=Cell(True, 3), taken=True, dest_pc=11, dest_fp=200,
            inverse=Cell(True, pow_inverse(3)), new_frame=Cell(True, 0xBAD),
        )
        self.assertIs(bad_fp.status, Status.BAD_POINTER)


# --- BLAKE3 service offload. ------------------------------------------------


class Blake3ServiceTests(unittest.TestCase):
    def request(self, endpoint: Lsc1Endpoint, txn_id: int = 1) -> lsc1.ResponseFrame:
        frame = lsc1.build_blake3(
            txn_id=txn_id, pc=2, fp=64, profile=Profile.INTERPRETER_COMPAT,
            message_offsets=(0, 1, 2, 3), cv_offset=8, out_offset=10, metadata=0x40,
            message_cells=(Cell(True, 11), Cell(True, 22), Cell(True, 33), Cell(True, 44)),
            cv_cells=(Cell(True, 55), Cell(True, 66)), out_cells=(ABSENT, ABSENT),
        )
        return exchange(endpoint, frame)

    def test_request_suspends_the_transaction_and_publishes_the_operands(self) -> None:
        endpoint = Lsc1Endpoint()
        reply = self.request(endpoint)
        self.assertIs(reply.status, Status.SERVICE_REQUIRED)
        self.assertIs(endpoint.state, TxnState.SERVICE_PENDING)
        reader = lsc1._Reader(reply.payload)
        self.assertEqual(reader.u32(), 1)
        service_id = reader.u32()
        self.assertEqual(reader.u8(), int(lsc1.ServiceKind.BLAKE3_COMPRESS))
        self.assertEqual(reader.u8(), 0)
        self.assertEqual([reader.f128() for _ in range(4)], [11, 22, 33, 44])
        self.assertEqual([reader.f128() for _ in range(2)], [55, 66])
        self.assertEqual(reader.f128(), 0x40)
        reader.done()
        self.assertEqual(service_id, 1)

    def test_response_writes_the_digest_and_resumes_the_transaction(self) -> None:
        endpoint = Lsc1Endpoint()
        self.request(endpoint)
        staged = endpoint.staged
        assert staged is not None and staged.service is not None
        reply = exchange(
            endpoint,
            lsc1.build_service_response(
                txn_id=1, service_id=staged.service.service_id, digest=(0xAA, 0xBB)
            ),
        )
        self.assertIs(reply.status, Status.OK)
        self.assertIs(endpoint.state, TxnState.RESULT_PENDING)
        self.assertEqual(
            staged.writes, [lsc1.Write(74, 0xAA), lsc1.Write(75, 0xBB)]
        )
        self.assertEqual(staged.accesses, [64, 65, 66, 67, 72, 73, 74, 75])
        self.assertIs(retire(endpoint).status, Status.RETIRED)
        self.assertEqual((endpoint.committed_pc, endpoint.committed_fp), (3, 64))

    def test_a_response_for_the_wrong_transaction_or_service_is_refused(self) -> None:
        for txn_id, service_id, detail in ((2, 1, "txn"), (1, 99, "service")):
            with self.subTest(detail=detail):
                endpoint = Lsc1Endpoint()
                self.request(endpoint)
                reply = exchange(
                    endpoint,
                    lsc1.build_service_response(
                        txn_id=txn_id, service_id=service_id, digest=(1, 2)
                    ),
                )
                self.assertIs(reply.status, Status.BAD_SERVICE)

    def test_a_refused_service_response_leaves_the_transaction_retryable(self) -> None:
        """`BAD_SERVICE` is checked before the digest folds in, so §9.1 puts it
        in the reject-this-frame-only class."""
        endpoint = Lsc1Endpoint()
        self.request(endpoint)
        refused = exchange(
            endpoint,
            lsc1.build_service_response(txn_id=1, service_id=99, digest=(7, 8)),
        )
        self.assertIs(refused.status, Status.BAD_SERVICE)
        self.assertIs(endpoint.state, TxnState.SERVICE_PENDING)
        resumed = exchange(
            endpoint,
            lsc1.build_service_response(txn_id=1, service_id=1, digest=(7, 8)),
        )
        self.assertIs(resumed.status, Status.OK)
        self.assertIs(endpoint.state, TxnState.RESULT_PENDING)

    def test_a_response_of_the_wrong_kind_is_refused(self) -> None:
        endpoint = Lsc1Endpoint()
        self.request(endpoint)
        payload = bytearray(
            lsc1.build_service_response(txn_id=1, service_id=1, digest=(1, 2)).payload
        )
        payload[8] = 0x02
        reply = exchange(endpoint, lsc1.RequestFrame(Opcode.SERVICE_RESPONSE, bytes(payload)))
        self.assertIs(reply.status, Status.BAD_SERVICE)

    def test_an_unsolicited_service_response_is_refused(self) -> None:
        endpoint = Lsc1Endpoint()
        reply = exchange(
            endpoint, lsc1.build_service_response(txn_id=1, service_id=1, digest=(1, 2))
        )
        self.assertIs(reply.status, Status.BAD_STATE)

    def test_a_suspended_transaction_refuses_a_new_instruction(self) -> None:
        endpoint = Lsc1Endpoint()
        self.request(endpoint)
        self.assertIs(exchange(endpoint, simple_xor(pc=2)).status, Status.BAD_STATE)
        self.assertIs(endpoint.state, TxnState.SERVICE_PENDING)

    def test_a_digest_colliding_with_a_written_output_is_a_write_conflict(self) -> None:
        endpoint = Lsc1Endpoint()
        frame = lsc1.build_blake3(
            txn_id=1, pc=2, fp=64, profile=Profile.INTERPRETER_COMPAT,
            message_offsets=(0, 1, 2, 3), cv_offset=8, out_offset=10, metadata=0,
            message_cells=(Cell(True, 1), Cell(True, 2), Cell(True, 3), Cell(True, 4)),
            cv_cells=(Cell(True, 5), Cell(True, 6)),
            out_cells=(Cell(True, 0x1111), ABSENT),
        )
        self.assertIs(exchange(endpoint, frame).status, Status.SERVICE_REQUIRED)
        staged = endpoint.staged
        assert staged is not None and staged.service is not None
        reply = exchange(
            endpoint,
            lsc1.build_service_response(
                txn_id=1, service_id=staged.service.service_id, digest=(0x2222, 0)
            ),
        )
        self.assertIs(reply.status, Status.WRITE_CONFLICT)
        self.assertIsNone(endpoint.staged)


# --- Retirement and the trust boundary. -------------------------------------


class RetirementTests(unittest.TestCase):
    def test_no_committed_state_moves_before_retirement(self) -> None:
        endpoint = Lsc1Endpoint()
        self.assertIs(exchange(endpoint, simple_xor(pc=0, fp=64)).status, Status.OK)
        self.assertEqual(endpoint.committed_pc, 0)
        self.assertEqual(endpoint.committed_fp, 0)
        self.assertFalse(endpoint.state_valid)
        self.assertEqual(endpoint.retire_seq, 0)
        self.assertIs(retire(endpoint).status, Status.RETIRED)
        self.assertEqual(endpoint.committed_pc, 1)
        self.assertEqual(endpoint.committed_fp, 64)
        self.assertTrue(endpoint.state_valid)
        self.assertEqual(endpoint.retire_seq, 1)

    def test_a_transaction_retires_exactly_once(self) -> None:
        endpoint = Lsc1Endpoint()
        exchange(endpoint, simple_xor(txn_id=7))
        staged = endpoint.staged
        assert staged is not None
        frame = lsc1.build_retire(txn_id=7, result_crc=staged.result_crc)
        self.assertIs(exchange(endpoint, frame).status, Status.RETIRED)
        for _ in range(3):
            self.assertIs(exchange(endpoint, frame).status, Status.BAD_STATE)
        self.assertEqual(endpoint.retire_seq, 1)

    def test_retirement_reports_the_new_committed_state(self) -> None:
        endpoint = Lsc1Endpoint()
        exchange(endpoint, simple_xor(txn_id=7, pc=3, fp=64))
        reply = retire(endpoint)
        reader = lsc1._Reader(reply.payload)
        self.assertEqual(reader.u32(), 7)
        self.assertEqual(reader.u32(), 1)
        self.assertEqual(reader.u32(), 4)
        self.assertEqual(reader.u32(), 64)
        reader.done()

    def test_retirement_is_bound_to_the_result_the_host_actually_read(self) -> None:
        endpoint = Lsc1Endpoint()
        exchange(endpoint, simple_xor(txn_id=7))
        staged = endpoint.staged
        assert staged is not None
        wrong = lsc1.build_retire(txn_id=7, result_crc=staged.result_crc ^ 1)
        self.assertIs(exchange(endpoint, wrong).status, Status.RETIRE_MISMATCH)
        self.assertEqual(endpoint.retire_seq, 0)
        self.assertIs(endpoint.state, TxnState.IDLE)

    def test_retirement_is_bound_to_the_transaction_id(self) -> None:
        endpoint = Lsc1Endpoint()
        exchange(endpoint, simple_xor(txn_id=7))
        staged = endpoint.staged
        assert staged is not None
        wrong = lsc1.build_retire(txn_id=8, result_crc=staged.result_crc)
        self.assertIs(exchange(endpoint, wrong).status, Status.RETIRE_MISMATCH)
        self.assertEqual(endpoint.retire_seq, 0)

    def test_the_result_crc_covers_the_whole_result_payload(self) -> None:
        endpoint = Lsc1Endpoint()
        reply = exchange(endpoint, simple_xor(txn_id=7))
        staged = endpoint.staged
        assert staged is not None
        self.assertEqual(staged.result_crc, ref_crc32(reply.payload))

    def test_retirement_without_a_staged_transaction_is_refused(self) -> None:
        endpoint = Lsc1Endpoint()
        reply = exchange(endpoint, lsc1.build_retire(txn_id=1, result_crc=0))
        self.assertIs(reply.status, Status.BAD_STATE)

    def test_only_one_transaction_is_outstanding_at_a_time(self) -> None:
        endpoint = Lsc1Endpoint()
        exchange(endpoint, simple_xor(txn_id=1))
        self.assertIs(exchange(endpoint, simple_xor(txn_id=2)).status, Status.BAD_STATE)
        self.assertIs(endpoint.state, TxnState.RESULT_PENDING)
        staged = endpoint.staged
        assert staged is not None
        self.assertEqual(staged.txn_id, 1)

    def test_a_rejected_frame_does_not_disturb_the_outstanding_transaction(self) -> None:
        # A duplicate, corrupt or ill-timed frame is a rejection of that frame,
        # not a cancellation of work the endpoint already decided.
        endpoint = Lsc1Endpoint()
        exchange(endpoint, simple_xor(txn_id=1))
        staged = endpoint.staged
        assert staged is not None
        intruders = [
            simple_xor(txn_id=2),
            lsc1.build_negotiate(profile=Profile.FORWARD_ONLY),
            lsc1.build_service_response(txn_id=1, service_id=1, digest=(1, 2)),
            lsc1.RequestFrame(Opcode.XOR, simple_xor().payload, flags=0x01),
        ]
        for intruder in intruders:
            with self.subTest(opcode=intruder.opcode):
                self.assertGreaterEqual(int(exchange(endpoint, intruder).status), 0x80)
                self.assertIs(endpoint.state, TxnState.RESULT_PENDING)
                self.assertIs(endpoint.staged, staged)
        self.assertIs(retire(endpoint).status, Status.RETIRED)
        self.assertEqual(endpoint.retire_seq, 1)

    def test_a_rejected_frame_does_not_disturb_a_suspended_service(self) -> None:
        endpoint = Lsc1Endpoint()
        frame = lsc1.build_blake3(
            txn_id=1, pc=0, fp=64, profile=Profile.INTERPRETER_COMPAT,
            message_offsets=(0, 1, 2, 3), cv_offset=8, out_offset=10, metadata=0,
            message_cells=(Cell(True, 1), Cell(True, 2), Cell(True, 3), Cell(True, 4)),
            cv_cells=(Cell(True, 5), Cell(True, 6)), out_cells=(ABSENT, ABSENT),
        )
        self.assertIs(exchange(endpoint, frame).status, Status.SERVICE_REQUIRED)
        staged = endpoint.staged
        assert staged is not None and staged.service is not None
        self.assertIs(exchange(endpoint, lsc1.build_retire(txn_id=1, result_crc=0)).status,
                      Status.BAD_STATE)
        self.assertIs(endpoint.state, TxnState.SERVICE_PENDING)
        self.assertIs(endpoint.staged, staged)
        reply = exchange(
            endpoint,
            lsc1.build_service_response(
                txn_id=1, service_id=staged.service.service_id, digest=(1, 2)
            ),
        )
        self.assertIs(reply.status, Status.OK)

    def test_a_host_that_forks_the_scalar_state_is_rejected(self) -> None:
        endpoint = Lsc1Endpoint()
        exchange(endpoint, simple_xor(txn_id=1, pc=0, fp=64))
        retire(endpoint)
        stale = exchange(endpoint, simple_xor(txn_id=2, pc=0, fp=64))
        self.assertIs(stale.status, Status.STATE_MISMATCH)
        fresh = exchange(endpoint, simple_xor(txn_id=2, pc=1, fp=64))
        self.assertIs(fresh.status, Status.OK)

    def test_a_sequence_of_transactions_advances_pc_monotonically(self) -> None:
        endpoint = Lsc1Endpoint()
        for step in range(6):
            self.assertIs(exchange(endpoint, simple_xor(txn_id=step, pc=step)).status, Status.OK)
            self.assertIs(retire(endpoint).status, Status.RETIRED)
            self.assertEqual(endpoint.committed_pc, step + 1)
            self.assertEqual(endpoint.retire_seq, step + 1)

    def test_status_query_reports_the_committed_state_without_changing_it(self) -> None:
        endpoint = Lsc1Endpoint()
        exchange(endpoint, simple_xor(txn_id=42))
        reply = exchange(endpoint, lsc1.build_status_query())
        self.assertIs(reply.status, Status.INFO)
        reader = lsc1._Reader(reply.payload)
        self.assertEqual(reader.u8(), 0x01)
        self.assertEqual(reader.u32(), 42)
        reader.u8()
        self.assertEqual(reader.u32(), 0)
        reader.u8()
        self.assertEqual(reader.u32(), 0)
        self.assertEqual(reader.u32(), 0)
        self.assertEqual(reader.u8(), 0)
        reader.done()
        self.assertIs(endpoint.state, TxnState.RESULT_PENDING)
        self.assertIs(retire(endpoint).status, Status.RETIRED)

    def test_pc_and_fp_beyond_the_verifiable_index_range_are_refused(self) -> None:
        for pc, fp in ((lsc1.INDEX_LIMIT, 0), (0, lsc1.INDEX_LIMIT)):
            with self.subTest(pc=pc, fp=fp):
                endpoint = Lsc1Endpoint()
                reply = exchange(endpoint, simple_xor(pc=pc, fp=fp))
                self.assertIs(reply.status, Status.INDEX_RANGE)


# --- Budgets. ---------------------------------------------------------------


class BudgetTests(unittest.TestCase):
    def test_budget_request_bytes_match_the_codec(self) -> None:
        for entry in lsc1.budget_table():
            self.assertEqual(
                entry.request_bytes,
                REQUEST_HEADER_BYTES + REQUEST_PAYLOAD_BYTES[entry.opcode] + CRC_BYTES,
            )

    def test_budget_result_bytes_bound_every_observed_result_frame(self) -> None:
        observed = {
            Opcode.XOR: simple_xor(),
            Opcode.SET_CONSTANT: lsc1.build_set_constant(
                txn_id=1, pc=0, fp=64, profile=Profile.INTERPRETER_COMPAT,
                offset=1, constant=3, cell=ABSENT,
            ),
            Opcode.DEREF_CELL: lsc1.build_deref(
                Opcode.DEREF_CELL, txn_id=1, pc=0, fp=64,
                profile=Profile.INTERPRETER_COMPAT, alpha=0, beta=2, gamma=3,
                pointer=pointer_cell(40), base=40, target=ABSENT, local=Cell(True, 9),
            ),
        }
        for opcode, frame in observed.items():
            with self.subTest(opcode=opcode.name):
                endpoint = Lsc1Endpoint()
                reply = exchange(endpoint, frame)
                self.assertIs(reply.status, Status.OK)
                self.assertLessEqual(
                    lsc1.response_frame_bytes(len(reply.payload)),
                    lsc1.budget(opcode).result_bytes,
                )

    def test_budget_cycles_bound_every_observed_execution(self) -> None:
        cases = [
            (
                Opcode.MUL_NATIVE,
                lsc1.build_binary_op(
                    Opcode.MUL_NATIVE, txn_id=1, pc=0, fp=64,
                    profile=Profile.INTERPRETER_COMPAT, offsets=(1, 2, 3),
                    cells=(ABSENT, Cell(True, 9), Cell(True, 0x33)),
                    proposed_inverse=Cell(True, pow_inverse(9)),
                ),
            ),
            (
                Opcode.DEREF_PC,
                lsc1.build_deref(
                    Opcode.DEREF_PC, txn_id=1, pc=0, fp=64,
                    profile=Profile.INTERPRETER_COMPAT, alpha=0, beta=2, gamma=3,
                    pointer=pointer_cell(40), base=40, target=ABSENT, local=ABSENT,
                ),
            ),
            (
                Opcode.JUMP,
                lsc1.build_jump(
                    txn_id=1, pc=0, fp=64, profile=Profile.INTERPRETER_COMPAT,
                    offsets=(0, 1, 2),
                    cells=(Cell(True, 3), pointer_cell(11), pointer_cell(200)),
                    taken=True, dest_pc=11, dest_fp=200,
                    proposed_inverse=Cell(True, pow_inverse(3)),
                ),
            ),
        ]
        for opcode, frame in cases:
            with self.subTest(opcode=opcode.name):
                endpoint = Lsc1Endpoint()
                self.assertIs(exchange(endpoint, frame).status, Status.OK)
                staged = endpoint.staged
                assert staged is not None
                self.assertLessEqual(
                    staged.execute_cycles, lsc1.budget(opcode).execute_cycles
                )

    def test_forward_only_never_costs_more_than_interpreter_compatibility(self) -> None:
        for opcode in lsc1.INSTRUCTION_OPCODES:
            with self.subTest(opcode=opcode.name):
                self.assertLessEqual(
                    lsc1.budget(opcode, Profile.FORWARD_ONLY).execute_cycles,
                    lsc1.budget(opcode, Profile.INTERPRETER_COMPAT).execute_cycles,
                )

    def test_round_trip_cycles_are_positive_and_dominated_by_the_multiplier(self) -> None:
        table = {entry.opcode: entry for entry in lsc1.budget_table()}
        for entry in table.values():
            self.assertGreater(entry.round_trip_cycles, 0)
        self.assertGreater(
            table[Opcode.JUMP].round_trip_cycles,
            table[Opcode.SET_CONSTANT].round_trip_cycles,
        )

    def test_no_stall_transaction_cycle_count_matches_the_byte_budget(self) -> None:
        endpoint = Lsc1Endpoint()
        request = simple_xor().encode()
        _, cycles = lsc1.drive(endpoint, request)
        staged = endpoint.staged
        assert staged is not None
        payload = staged.result_payload()
        self.assertEqual(
            cycles, len(request) + lsc1.response_frame_bytes(len(payload))
        )


if __name__ == "__main__":
    unittest.main()

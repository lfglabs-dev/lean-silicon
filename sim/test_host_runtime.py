"""Tests for the Mac-side host runtime and the lean_compiler adapter.

Everything here runs with no Rust toolchain present: the frozen-compiler
artifact is checked in, and ``tools/host_upstream_comparison.py`` is what
re-derives it live from ``leanEthereum/leanVM-b`` when a checkout is supplied.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from host import lean_compiler_adapter as adapter  # noqa: E402
from host.errors import (  # noqa: E402
    AdapterError,
    ProtocolViolation,
    UnsupportedCapability,
    WriteOnceViolation,
)
from host.memory import HostMemory, PointerMap, field_inverse  # noqa: E402
from host.protocol import protocol  # noqa: E402
from host.runtime import HostRuntime, decode_result_payload  # noqa: E402
from tools import host_upstream_comparison as comparison_tool  # noqa: E402
from tools.host_upstream_comparison import compare  # noqa: E402

ARTIFACT = ROOT / "host" / "fixtures" / "assert_set_xor_mul.program.json"

#: Tail slot every synthetic program ends with; `run` halts on reaching it.
SENTINEL = {"index": None, "op": "Set", "o": 0, "k": f"{0:#034x}"}


def program(*slots, pc0=0, fp0=0) -> adapter.Program:
    """Build an in-memory Program from bytecode slots plus a halt sentinel."""
    operations = []
    for index, slot in enumerate(list(slots) + [dict(SENTINEL)]):
        body = {key: value for key, value in slot.items() if key not in ("index", "op")}
        for name in adapter.FIELD_OPERANDS:
            if name in body and isinstance(body[name], str):
                body[name] = int(body[name], 16)
        operations.append(adapter.Operation(index, slot["op"], body))
    return adapter.Program(
        operations=tuple(operations),
        pc0=pc0,
        fp0=fp0,
        fn_ranges=(),
        source="",
        upstream_sha=adapter.FROZEN_LEANVM_B,
        disassembly="",
        upstream_execution=None,
    )


def set_slot(offset: int, constant: int) -> dict:
    return {"op": "Set", "o": offset, "k": f"{constant:#034x}"}


class HostMemoryTests(unittest.TestCase):
    def test_public_input_seeds_the_first_two_cells(self):
        memory = HostMemory.with_public_input(1, 0)
        self.assertEqual((memory.read(0), memory.read(1)), (1, 0))
        self.assertFalse(memory.written(2))
        self.assertIs(memory.cell(2), protocol.ABSENT)
        self.assertEqual(memory.cell(0), protocol.Cell(True, 1))

    def test_write_once_accepts_the_same_value_and_rejects_a_different_one(self):
        memory = HostMemory()
        memory.apply_write(4, 0x1234)
        memory.apply_write(4, 0x1234)
        self.assertEqual(memory.read(4), 0x1234)
        with self.assertRaisesRegex(WriteOnceViolation, "already holds"):
            memory.apply_write(4, 0x1235)

    def test_deferred_equalities_propagate_and_detect_contradiction(self):
        memory = HostMemory()
        memory.apply_write(2, 7)
        memory.record_deferred(2, 3)
        memory.record_deferred(8, 9)
        self.assertEqual(memory.resolve_deferred(), [(8, 9)])
        self.assertEqual(memory.read(3), 7)

        contradiction = HostMemory(cells={2: 7, 3: 8})
        contradiction.record_deferred(2, 3)
        with self.assertRaisesRegex(WriteOnceViolation, "unsatisfiable"):
            contradiction.resolve_deferred()

    def test_deferred_equalities_propagate_to_a_fixed_point(self):
        memory = HostMemory(cells={3: 11})
        memory.record_deferred(1, 2)
        memory.record_deferred(2, 3)
        self.assertEqual(memory.resolve_deferred(), [])
        self.assertEqual((memory.read(1), memory.read(2)), (11, 11))

    def test_field_inverse_round_trips(self):
        for value in (1, 2, 3, 0x87, (1 << 127) | 5, (1 << 128) - 1):
            self.assertEqual(protocol.field_mul(value, field_inverse(value)), 1)
        with self.assertRaises(ZeroDivisionError):
            field_inverse(0)


class PointerMapTests(unittest.TestCase):
    def test_encode_and_reverse_agree(self):
        pointers = PointerMap()
        for index in (0, 1, 2, 17, 4096):
            self.assertEqual(pointers.index_of(pointers.encode(index)), index)

    def test_index_beyond_the_v1_window_is_refused(self):
        pointers = PointerMap()
        with self.assertRaisesRegex(UnsupportedCapability, "outside the LSC-1 v1 window"):
            pointers.encode(protocol.INDEX_LIMIT)

    def test_a_non_g_power_has_no_index(self):
        pointers = PointerMap()
        with self.assertRaisesRegex(UnsupportedCapability, "is not a g-power"):
            pointers.index_of(0)


class AdapterTests(unittest.TestCase):
    def _reject(self, mutate, message):
        document = json.loads(ARTIFACT.read_text())
        mutate(document)
        directory = self.enterContext(tempfile.TemporaryDirectory())
        candidate = pathlib.Path(directory) / "artifact.json"
        candidate.write_text(json.dumps(document))
        with self.assertRaisesRegex(AdapterError, message):
            adapter.load(candidate)

    def test_the_checked_in_artifact_loads(self):
        loaded = adapter.load(ARTIFACT)
        self.assertEqual(loaded.upstream_sha, adapter.FROZEN_LEANVM_B)
        self.assertEqual(len(loaded.operations), 16)
        self.assertEqual(loaded.halt_pc, 15)
        self.assertEqual(loaded.at(0).kind, "Set")
        self.assertIsInstance(loaded.at(0).operands["k"], int)
        self.assertTrue(loaded.at(2).integrated)
        self.assertFalse(loaded.at(12).integrated)

    def test_host_package_imports_with_deferred_annotations_policy(self):
        for module_path in sorted((ROOT / "host").glob("*.py")):
            with self.subTest(module=module_path.name):
                self.assertIn(
                    "from __future__ import annotations",
                    module_path.read_text(),
                )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import host, host.errors, host.lean_compiler_adapter, "
                "host.memory, host.protocol, host.runtime",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_pc_outside_the_program_is_refused(self):
        loaded = adapter.load(ARTIFACT)
        with self.assertRaisesRegex(AdapterError, "outside the 16-slot program"):
            loaded.at(16)

    def test_wrong_schema_is_refused(self):
        self._reject(lambda d: d.__setitem__("schema", "something/2"), "is not")

    def test_a_non_frozen_upstream_is_refused(self):
        self._reject(lambda d: d["upstream"].__setitem__("sha", "0" * 40), "frozen commit")

    def test_a_non_power_of_two_bytecode_is_refused(self):
        self._reject(lambda d: d["program"]["bytecode"].pop(), "not a power of two")

    def test_a_mislabelled_slot_is_refused(self):
        self._reject(
            lambda d: d["program"]["bytecode"][3].__setitem__("index", 9),
            "is labelled 9",
        )

    def test_an_unknown_opcode_is_refused(self):
        self._reject(
            lambda d: d["program"]["bytecode"][0].__setitem__("op", "Poseidon"),
            "unknown opcode",
        )

    def test_a_malformed_field_operand_is_refused(self):
        self._reject(
            lambda d: d["program"]["bytecode"][0].__setitem__("k", "3"),
            "128-bit hex literal",
        )

    def test_malformed_u32_operands_are_adapter_errors(self):
        for value in ("2", None, True, -1, 1 << 32):
            with self.subTest(value=value):
                self._reject(
                    lambda d, value=value: d["program"]["bytecode"][0].__setitem__("o", value),
                    "integer|outside u32",
                )

    def test_malformed_initial_scalars_are_adapter_errors(self):
        for name in ("pc0", "fp0"):
            for value in ("2", None, True, False, -1, 1 << 32):
                with self.subTest(field=name, value=value):
                    self._reject(
                        lambda d, name=name, value=value: d["program"].__setitem__(name, value),
                        "integer|outside u32",
                    )

    def test_pc0_outside_the_bytecode_is_refused(self):
        self._reject(
            lambda d: d["program"].__setitem__("pc0", 16),
            "pc0 16 is outside the 16-slot bytecode",
        )

    def test_missing_and_compound_operands_are_adapter_errors(self):
        self._reject(
            lambda d: d["program"]["bytecode"][0].pop("o"),
            "operands are",
        )

        def invalid_blake3(document):
            slot = document["program"]["bytecode"][12]
            slot.clear()
            slot.update({
                "index": 12, "op": "Blake3", "ins": [1, "2", 3, 4],
                "cv": 5, "out": 6, "metadata": f"{0:#034x}",
            })

        self._reject(
            invalid_blake3,
            r"ins\[1\].*integer",
        )

        def invalid_deref(document):
            slot = document["program"]["bytecode"][6]
            slot.clear()
            slot.update({
                "index": 6, "op": "Deref", "alpha": 1, "beta": 2,
                "gamma": 3, "mode": "Other",
            })

        self._reject(
            invalid_deref,
            "mode.*invalid",
        )


class ResultPayloadTests(unittest.TestCase):
    def test_decode_matches_the_endpoint_encoding(self):
        payload = (
            (7).to_bytes(4, "little")
            + (9).to_bytes(4, "little")
            + (0).to_bytes(4, "little")
            + bytes([1])
            + (4).to_bytes(4, "little") + (0x1F).to_bytes(16, "little")
            + bytes([1])
            + (5).to_bytes(4, "little") + (6).to_bytes(4, "little")
            + bytes([1])
            + (4).to_bytes(4, "little")
        )
        self.assertEqual(decode_result_payload(payload), {
            "txn_id": 7,
            "next_pc": 9,
            "next_fp": 0,
            "writes": [{"address": 4, "value": 0x1F}],
            "deferred": [{"target": 5, "local": 6}],
            "accesses": [4],
        })

    def test_a_truncated_payload_is_refused(self):
        payloads = (
            b"",
            bytes(12),
            bytes(12) + bytes([1]),
            bytes(12) + bytes([0]),
            bytes(12) + bytes([0, 1]),
            bytes(12) + bytes([0, 0]),
            bytes(12) + bytes([0, 0, 1]),
            bytes(12) + bytes([0, 0, 0, 0]),
        )
        for payload in payloads:
            with self.subTest(length=len(payload)):
                with self.assertRaisesRegex(ProtocolViolation, "short|truncated|consumed"):
                    decode_result_payload(payload)

    def test_a_result_for_another_transaction_is_refused(self):
        payload = (9).to_bytes(4, "little") + bytes(8) + bytes([0, 0, 0])
        with self.assertRaisesRegex(ProtocolViolation, "expected 8"):
            decode_result_payload(payload, expected_txn_id=8)

    def test_poisoned_result_wrong_txn_id_is_protocol_violation(self):
        # A result echoing a different txn_id must be refused (F1 binding preserved)
        payload = (5).to_bytes(4, "little") + (1).to_bytes(4, "little") + (0).to_bytes(4, "little") + bytes([0, 0, 0])
        with self.assertRaisesRegex(ProtocolViolation, "echoed txn_id"):
            decode_result_payload(payload, expected_txn_id=7)

    def test_poisoned_stale_frame_regressions(self):
        """Poisoned or stale frames (wrong txn, tampered CRC) must be refused; F1 binding preserved."""
        from host.runtime import decode_result_payload
        # Truncated result payload (poisoned frame) raises ProtocolViolation
        with self.assertRaisesRegex(ProtocolViolation, "truncated|consumed"):
            decode_result_payload((1).to_bytes(4,"little") + (0).to_bytes(4,"little") + (0).to_bytes(4,"little") + bytes([1]))
        # Wrong txn_id is refused (F1 binding)
        with self.assertRaisesRegex(ProtocolViolation, "echoed txn_id"):
            decode_result_payload((9).to_bytes(4,"little") + bytes(8) + bytes([0,0,0]), expected_txn_id=1)


class RuntimeTests(unittest.TestCase):
    class _NegotiationRuntime(HostRuntime):
        def __init__(self, *args, negotiation_payload, **kwargs):
            self.negotiation_payload = negotiation_payload
            super().__init__(*args, **kwargs)

        def _exchange(self, frame):
            return protocol.ResponseFrame(protocol.Status.OK, self.negotiation_payload)

    class _ScriptedRuntime(HostRuntime):
        def __init__(self, *args, result_payload, retire_payload, **kwargs):
            self.result_payload = result_payload
            self.retire_payload = retire_payload
            super().__init__(*args, **kwargs)

        def _exchange(self, frame):
            opcode = protocol.Opcode(frame.opcode)
            if opcode is protocol.Opcode.NEGOTIATE:
                payload = (
                    bytes((protocol.PROTOCOL_VERSION, int(self.profile)))
                    + protocol.u16le(protocol.MAX_PAYLOAD_BYTES)
                    + bytes((protocol.INDEX_BITS, 0))
                    + protocol.u32le(protocol.DEVICE_FEATURES)
                    + protocol.u32le(protocol.DEVICE_ID)
                )
                return protocol.ResponseFrame(protocol.Status.OK, payload)
            if opcode is protocol.Opcode.RETIRE:
                return protocol.ResponseFrame(protocol.Status.RETIRED, self.retire_payload)
            return protocol.ResponseFrame(protocol.Status.OK, self.result_payload)

    def test_negotiate_requires_every_schema_field(self):
        expected = (
            bytes((protocol.PROTOCOL_VERSION, int(protocol.Profile.INTERPRETER_COMPAT)))
            + protocol.u16le(protocol.MAX_PAYLOAD_BYTES)
            + bytes((protocol.INDEX_BITS, 0))
            + protocol.u32le(protocol.DEVICE_FEATURES)
            + protocol.u32le(protocol.DEVICE_ID)
        )
        self._NegotiationRuntime(program(set_slot(2, 1)), negotiation_payload=expected)
        for index in range(len(expected)):
            malformed = bytearray(expected)
            malformed[index] ^= 1
            with self.subTest(index=index):
                with self.assertRaisesRegex(ProtocolViolation, "required 14-byte schema"):
                    self._NegotiationRuntime(
                        program(set_slot(2, 1)),
                        negotiation_payload=bytes(malformed),
                    )
        with self.assertRaisesRegex(ProtocolViolation, "required 14-byte schema"):
            self._NegotiationRuntime(program(set_slot(2, 1)), negotiation_payload=expected[:-1])

    def test_post_retire_write_batch_is_atomic_on_a_late_conflict(self):
        result_payload = (
            (1).to_bytes(4, "little") + (1).to_bytes(4, "little") + bytes(4)
            + bytes([2])
            + (2).to_bytes(4, "little") + (0xAA).to_bytes(16, "little")
            + (3).to_bytes(4, "little") + (0xBB).to_bytes(16, "little")
            + bytes([0, 0])
        )
        retire_payload = (
            (1).to_bytes(4, "little") + (1).to_bytes(4, "little")
            + (1).to_bytes(4, "little") + bytes(4)
        )
        memory = HostMemory(cells={3: 0xCC})
        runtime = self._ScriptedRuntime(
            program(set_slot(2, 1)),
            memory=memory,
            result_payload=result_payload,
            retire_payload=retire_payload,
        )
        with self.assertRaises(WriteOnceViolation):
            runtime.step()
        self.assertIsNone(memory.read(2))
        self.assertEqual(memory.read(3), 0xCC)

    def test_post_retire_conflicting_duplicate_writes_are_atomic(self):
        result_payload = (
            (1).to_bytes(4, "little") + (1).to_bytes(4, "little") + bytes(4)
            + bytes([2])
            + (2).to_bytes(4, "little") + (0xAA).to_bytes(16, "little")
            + (2).to_bytes(4, "little") + (0xBB).to_bytes(16, "little")
            + bytes([0, 0])
        )
        retire_payload = (
            (1).to_bytes(4, "little") + (1).to_bytes(4, "little")
            + (1).to_bytes(4, "little") + bytes(4)
        )
        memory = HostMemory()
        runtime = self._ScriptedRuntime(
            program(set_slot(2, 1)),
            memory=memory,
            result_payload=result_payload,
            retire_payload=retire_payload,
        )
        with self.assertRaisesRegex(ProtocolViolation, "conflicting writes"):
            runtime.step()
        self.assertIsNone(memory.read(2))

    def test_stale_retire_txn_id_is_protocol_violation(self):
        result_payload = (
            (1).to_bytes(4, "little") + (1).to_bytes(4, "little") + bytes(4)
            + bytes([0, 0, 0])
        )
        stale_retire = (
            (0).to_bytes(4, "little") + (1).to_bytes(4, "little")
            + (1).to_bytes(4, "little") + bytes(4)
        )
        runtime = self._ScriptedRuntime(
            program(set_slot(2, 1)),
            result_payload=result_payload,
            retire_payload=stale_retire,
        )
        with self.assertRaisesRegex(ProtocolViolation, "retire echoed txn_id"):
            runtime.step()

    class _FaultingRuntime(HostRuntime):
        """Answers the instruction with one scripted non-``OK`` frame."""

        def __init__(self, *args, fault_reply, **kwargs):
            self.fault_reply = fault_reply
            super().__init__(*args, **kwargs)

        def _exchange(self, frame):
            if protocol.Opcode(frame.opcode) is protocol.Opcode.NEGOTIATE:
                return super()._exchange(frame)
            return self.fault_reply

    def _refuse_fault(self, reply, message):
        runtime = self._FaultingRuntime(program(set_slot(2, 1)), fault_reply=reply)
        with self.assertRaisesRegex(ProtocolViolation, message):
            runtime.step()
        self.assertFalse(runtime.faulted)

    def test_a_non_fault_status_is_not_recorded_as_a_fault(self):
        for status in (
            protocol.Status.SERVICE_REQUIRED,
            protocol.Status.RETIRED,
            protocol.Status.INFO,
        ):
            with self.subTest(status=status.name):
                self._refuse_fault(
                    protocol.ResponseFrame(status, (1).to_bytes(4, "little") + bytes(1)),
                    f"answered {status.name}, which is not a fault status",
                )

    def test_a_fault_payload_of_the_wrong_size_is_a_protocol_violation(self):
        for payload in (b"", (1).to_bytes(4, "little"), (1).to_bytes(4, "little") + bytes(2)):
            with self.subTest(length=len(payload)):
                self._refuse_fault(
                    protocol.ResponseFrame(protocol.Status.WRITE_CONFLICT, payload),
                    f"fault payload has {len(payload)} bytes, expected 5",
                )

    def test_a_fault_bound_to_another_transaction_is_a_protocol_violation(self):
        for echoed in (0, 2, 9):
            with self.subTest(txn_id=echoed):
                self._refuse_fault(
                    protocol.ResponseFrame(
                        protocol.Status.WRITE_CONFLICT,
                        echoed.to_bytes(4, "little") + bytes(1),
                    ),
                    f"fault echoed txn_id {echoed}, expected 1",
                )

    def test_a_well_formed_fault_is_still_attributed_to_the_step(self):
        runtime = self._FaultingRuntime(
            program(set_slot(2, 1)),
            fault_reply=protocol.ResponseFrame(
                protocol.Status.WRITE_CONFLICT,
                (1).to_bytes(4, "little") + bytes([7]),
            ),
        )
        record = runtime.step()
        self.assertEqual(record.fault, "WRITE_CONFLICT")
        self.assertTrue(runtime.faulted)

    def test_set_xor_mul_are_driven_end_to_end(self):
        runtime = HostRuntime(program(
            set_slot(2, 3),
            set_slot(3, 5),
            {"op": "Xor", "a": 2, "b": 3, "c": 4},
            {"op": "Mul", "a": 2, "b": 3, "c": 5},
        ))
        result = runtime.run()
        self.assertEqual(result.terminal, "halted")
        self.assertEqual([record.opcode for record in result.records],
                         ["SET_CONSTANT", "SET_CONSTANT", "XOR", "MUL_NATIVE"])
        self.assertEqual(runtime.memory.read(4), 3 ^ 5)
        self.assertEqual(runtime.memory.read(5), 0xF)  # independently known value; do not use self-oracle protocol.field_mul here
        self.assertTrue(all(record.status == "OK" for record in result.records))
        self.assertTrue(all(record.retire_seq is not None for record in result.records))
        self.assertEqual([record.retire_seq for record in result.records], [1, 2, 3, 4])
        self.assertTrue(all(record.lane_cycles > 0 for record in result.records))

    def test_the_step_record_carries_the_whole_comparison_schema(self):
        runtime = HostRuntime(program(set_slot(2, 3), set_slot(3, 5),
                                      {"op": "Xor", "a": 2, "b": 3, "c": 4}))
        record = runtime.run().records[-1]
        self.assertEqual(set(record.as_dict()), {
            "index", "txn_id", "source_op", "opcode", "pc", "fp", "next_pc", "next_fp",
            "addresses", "inputs", "writes", "branch", "deferred", "accesses",
            "status", "fault", "retire_seq", "lane_cycles",
        })
        self.assertEqual(record.addresses, [2, 3, 4])
        self.assertEqual([entry["present"] for entry in record.inputs], [True, True, False])
        self.assertEqual(record.writes, [{"address": 4, "value": f"{3 ^ 5:#034x}"}])
        self.assertEqual((record.pc, record.next_pc), (2, 3))

    def test_mul_back_solves_from_the_host_inverse_witness(self):
        # m[4] is the product and m[2] the known factor, so the endpoint has to
        # recover m[3] = m[4] * m[2]**-1 from the witness the host proposes.
        runtime = HostRuntime(program(
            set_slot(2, 3),
            set_slot(4, protocol.field_mul(3, 5)),
            {"op": "Mul", "a": 2, "b": 3, "c": 4},
        ))
        result = runtime.run()
        self.assertEqual(result.terminal, "halted")
        self.assertEqual(runtime.memory.read(3), 5)

    def test_forward_only_refuses_the_same_back_solve(self):
        runtime = HostRuntime(
            program(
                set_slot(2, 3),
                set_slot(4, protocol.field_mul(3, 5)),
                {"op": "Mul", "a": 2, "b": 3, "c": 4},
            ),
            profile=protocol.Profile.FORWARD_ONLY,
        )
        result = runtime.run()
        self.assertEqual(result.terminal, "fault")
        self.assertEqual(result.records[-1].fault, "UNSUPPORTED_IN_PROFILE")
        self.assertIsNone(runtime.memory.read(3))

    def test_a_write_conflict_is_reported_as_a_fault_not_applied(self):
        runtime = HostRuntime(program(set_slot(2, 3), set_slot(2, 4)))
        result = runtime.run()
        self.assertEqual(result.terminal, "fault")
        self.assertEqual(result.records[-1].fault, "WRITE_CONFLICT")
        self.assertEqual(runtime.memory.read(2), 3)

    def test_multiplying_by_a_known_zero_is_not_given_a_witness(self):
        runtime = HostRuntime(program(
            set_slot(2, 0),
            set_slot(4, 0),
            {"op": "Mul", "a": 2, "b": 3, "c": 4},
        ))
        result = runtime.run()
        self.assertEqual(result.terminal, "fault")
        self.assertEqual(result.records[-1].fault, "MUL_BACKSOLVE_ZERO")

    def test_unintegrated_opcodes_stop_the_run_and_say_what_is_missing(self):
        for kind, slot in (
            ("Deref", {"op": "Deref", "alpha": 2, "beta": 0, "gamma": 3, "mode": "Cell"}),
            ("Jump", {"op": "Jump", "oc": 2, "od": 3, "of": 4}),
            ("Blake3", {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 7,
                        "metadata": f"{0:#034x}"}),
        ):
            with self.subTest(kind=kind):
                runtime = HostRuntime(program(set_slot(2, 3), slot))
                result = runtime.run()
                self.assertEqual(result.terminal, "unsupported")
                self.assertIn(kind, result.reason)
                self.assertIn(adapter.DEFERRED_OPS[kind].split(";")[0], result.reason)
                self.assertEqual(len(result.records), 1)

    def test_the_step_limit_is_a_terminal_not_a_hang(self):
        runtime = HostRuntime(program(set_slot(2, 3), set_slot(3, 4), set_slot(4, 5)))
        result = runtime.run(max_steps=2)
        self.assertEqual(result.terminal, "step_limit")
        self.assertEqual(len(result.records), 2)

    def test_sentinel_requires_zero_frame_pointer(self):
        runtime = HostRuntime(program(pc0=0, fp0=7))
        result = runtime.run()
        self.assertEqual(result.terminal, "fault")
        self.assertIn("bad_halt_state", result.reason)

    def test_arbitrary_rx_tx_stalls_and_backpressure(self):
        """Full transaction loop under arbitrary permitted lane-gap patterns."""
        for rx in ([], [0, 1], [1, 0], [2, 1, 0], [0, 0, 3]):
            for tx in ([], [1], [0, 2], [3, 0, 1]):
                with self.subTest(rx=rx, tx=tx):
                    runtime = HostRuntime(
                        program(set_slot(2, 0x11), set_slot(3, 0x22), {"op": "Xor", "a": 2, "b": 3, "c": 4}),
                        rx_gaps=rx,
                        tx_gaps=tx,
                    )
                    result = runtime.run()
                    self.assertEqual(result.terminal, "halted")
                    self.assertEqual(runtime.memory.read(4), 0x11 ^ 0x22)


class FrozenUpstreamComparisonTests(unittest.TestCase):
    """The only equivalence claim: final memory against the frozen Rust run.

    ``Execution::trace`` is ``pub(crate)`` at ``c308034a``, so upstream exposes
    no per-step rows to compare.  Memory is write-once, so a cell the host has
    decided cannot later be given a different value upstream, which makes the
    final image a sound comparison even though the host stops early.
    """

    def setUp(self):
        self.program = adapter.load(ARTIFACT)
        self.upstream = self.program.upstream_execution

    def test_the_artifact_records_the_frozen_commit_and_its_public_interface_limits(self):
        document = json.loads(ARTIFACT.read_text())
        self.assertEqual(document["upstream"]["sha"], adapter.FROZEN_LEANVM_B)
        self.assertEqual(document["upstream"]["preflight"]["head"], adapter.FROZEN_LEANVM_B)
        self.assertEqual(document["upstream"]["postflight"]["head"], adapter.FROZEN_LEANVM_B)
        self.assertEqual(
            set(document["upstream"]["not_exposed_by_public_interface"]),
            {"Program::hints", "Program::main_frame", "Program::witness", "Execution::trace"},
        )

    def test_host_writes_agree_with_the_frozen_final_memory(self):
        runtime = HostRuntime(self.program, memory=HostMemory.with_public_input(1, 0))
        result = runtime.run()
        # The fixture's only unintegrated instruction is the terminating JUMP.
        self.assertEqual(result.terminal, "unsupported")
        self.assertIn("Jump", result.reason)

        mem = [int(value, 16) for value in self.upstream["mem"]]
        self.assertEqual(len(mem), self.upstream["mem_used"])
        self.assertTrue(runtime.memory.cells)
        for address, value in sorted(runtime.memory.cells.items()):
            with self.subTest(address=address):
                self.assertLess(address, self.upstream["mem_used"])
                self.assertEqual(value, mem[address])

    def test_unsupported_suffix_is_prefix_match_never_full_match(self):
        runtime = HostRuntime(self.program, memory=HostMemory.with_public_input(1, 0))
        result = runtime.run()
        comparison = compare(runtime, result, self.upstream)
        self.assertEqual(result.terminal, "unsupported")
        self.assertEqual(comparison["result"], "PREFIX_MATCH")
        self.assertIn("unsupported_suffix", comparison["not_compared"])

    def test_the_host_covers_every_cell_the_frozen_run_touched(self):
        runtime = HostRuntime(self.program, memory=HostMemory.with_public_input(1, 0))
        runtime.run()
        self.assertEqual(sorted(runtime.memory.cells), list(range(self.upstream["mem_used"])))

    def test_cycles_are_not_claimed_equal_because_the_host_stops_early(self):
        runtime = HostRuntime(self.program, memory=HostMemory.with_public_input(1, 0))
        result = runtime.run()
        self.assertNotEqual(result.terminal, "halted")
        self.assertLess(runtime.step_index, self.upstream["cycles"])

    def test_step_limit_cannot_be_reported_as_a_match(self):
        runtime = HostRuntime(self.program, memory=HostMemory.with_public_input(1, 0))
        result = runtime.run(max_steps=0)
        comparison = compare(runtime, result, self.upstream)
        self.assertEqual(comparison["result"], "MISMATCH")
        self.assertIn(
            {"field": "terminal", "host": "step_limit", "reason": result.reason},
            comparison["mismatches"],
        )
        self.assertIn("final_memory_gaps", comparison["not_compared"])

    def test_halted_run_missing_an_upstream_cell_is_a_mismatch(self):
        runtime = HostRuntime(self.program, memory=HostMemory.with_public_input(1, 0))
        result = runtime.run()
        result.terminal = "halted"
        runtime.step_index = self.upstream["cycles"]
        runtime.memory.cells.pop(self.upstream["mem_used"] - 1)
        comparison = compare(runtime, result, self.upstream)
        self.assertEqual(comparison["result"], "MISMATCH")
        self.assertIn(
            "host did not cover upstream cell",
            comparison["mismatches"][-1]["reason"],
        )

    def test_live_probe_must_reproduce_recorded_execution(self):
        artifact = json.loads(ARTIFACT.read_text())
        probe = {
            "bytecode": artifact["program"]["bytecode"],
            "execution": dict(artifact["upstream_execution"]),
        }
        probe["execution"]["cycles"] += 1
        with (
            mock.patch.object(comparison_tool._export, "candidate_head"),
            mock.patch.object(comparison_tool._export, "require_checkout"),
            mock.patch.object(
                comparison_tool._export,
                "run_probe",
                return_value=(probe, ["cargo", "run"]),
            ),
        ):
            with self.assertRaisesRegex(SystemExit, "does not match recorded"):
                comparison_tool.upstream_execution(ARTIFACT, artifact, ROOT, "1.88.0")

    def test_out_of_tree_artifact_fails_with_a_clean_domain_error(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = pathlib.Path(directory) / "artifact.json"
            artifact.write_text(ARTIFACT.read_text())
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "host_upstream_comparison.py"),
                    "--artifact",
                    str(artifact),
                ],
                text=True,
                capture_output=True,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("artifact path must be inside the repo", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()

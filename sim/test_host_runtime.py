"""Tests for the Mac-side host runtime and the lean_compiler adapter.

Everything here runs with no Rust toolchain present: the frozen-compiler
artifact is checked in, and ``tools/host_upstream_comparison.py`` is what
re-derives it live from ``leanEthereum/leanVM-b`` when a checkout is supplied.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

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
from host.blake3_service import (  # noqa: E402
    ServiceInfrastructureError,
    ServiceSemanticError,
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
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = temporary.name
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
        self.assertTrue(loaded.at(12).integrated)

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
            #: Opcodes actually put on the wire, so a test can prove that a frame
            #: which would commit endpoint state was never sent.
            self.sent = []
            super().__init__(*args, **kwargs)

        def _exchange(self, frame):
            opcode = protocol.Opcode(frame.opcode)
            self.sent.append(opcode)
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

    def test_blake3_session_epoch_rejects_explicit_zero_and_retries_random_zero(self):
        with self.assertRaisesRegex(ValueError, "session_epoch must be a nonzero u64"):
            HostRuntime(program(set_slot(2, 1)), session_epoch=0)
        with mock.patch("host.runtime.secrets.randbits", side_effect=(0, 7)) as randbits:
            runtime = HostRuntime(program(set_slot(2, 1)))
        self.assertEqual(runtime.service_adapter.session_epoch, 7)
        self.assertEqual(randbits.call_count, 2)

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

    def test_a_write_once_conflict_is_refused_before_retire_is_sent(self):
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
        # RETIRE is what commits the endpoint's pc/fp. Sending it and only then
        # refusing the batch would advance the endpoint past a host that never
        # moved, which no retry can reconcile.
        self.assertNotIn(protocol.Opcode.RETIRE, runtime.sent)

    def test_conflicting_duplicate_writes_are_refused_before_retire_is_sent(self):
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
        self.assertNotIn(protocol.Opcode.RETIRE, runtime.sent)

    def test_an_invalid_deferred_equality_is_refused_before_retire_is_sent(self):
        result_payload = (
            (1).to_bytes(4, "little") + (1).to_bytes(4, "little") + bytes(4)
            + bytes([0])
            + bytes([1]) + (2).to_bytes(4, "little") + (3).to_bytes(4, "little")
            + bytes([0])
        )
        retire_payload = (
            (1).to_bytes(4, "little") + (1).to_bytes(4, "little")
            + (1).to_bytes(4, "little") + bytes(4)
        )
        memory = HostMemory(cells={2: 0xAA, 3: 0xBB})
        runtime = self._ScriptedRuntime(
            program(set_slot(2, 1)),
            memory=memory,
            result_payload=result_payload,
            retire_payload=retire_payload,
        )
        with self.assertRaisesRegex(WriteOnceViolation, "deferred equality 2 == 3"):
            runtime.step()
        self.assertEqual(memory.cells, {2: 0xAA, 3: 0xBB})
        self.assertNotIn(protocol.Opcode.RETIRE, runtime.sent)

    def test_an_acceptable_write_batch_is_still_retired_and_applied(self):
        """Guards the two tests above from passing because RETIRE never happens."""
        # An Xor so both written addresses are ones the frame actually carried;
        # a two-address batch is not a legal SET_CONSTANT frame.
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
        memory = HostMemory(cells={3: 0xBB})
        runtime = self._ScriptedRuntime(
            program({"op": "Xor", "a": 2, "b": 3, "c": 4}),
            memory=memory,
            result_payload=result_payload,
            retire_payload=retire_payload,
        )
        record = runtime.step()
        self.assertIn(protocol.Opcode.RETIRE, runtime.sent)
        self.assertIsNone(record.fault)
        self.assertEqual(memory.read(2), 0xAA)
        self.assertEqual(memory.read(3), 0xBB)

    def test_a_write_outside_the_frame_is_refused_before_retire_is_sent(self):
        # A SET_CONSTANT frame carries exactly one cell. A result that writes
        # some other address decided nothing about it: the host never sent that
        # cell, so the endpoint cannot have reasoned about its value.
        result_payload = (
            (1).to_bytes(4, "little") + (7).to_bytes(4, "little") + bytes(4)
            + bytes([1])
            + (9).to_bytes(4, "little") + (0xDEAD).to_bytes(16, "little")
            + bytes([0, 0])
        )
        retire_payload = (
            (1).to_bytes(4, "little") + (1).to_bytes(4, "little")
            + (7).to_bytes(4, "little") + bytes(4)
        )
        memory = HostMemory()
        runtime = self._ScriptedRuntime(
            program(set_slot(2, 1)),
            memory=memory,
            result_payload=result_payload,
            retire_payload=retire_payload,
        )
        with self.assertRaisesRegex(ProtocolViolation, "writes address 9"):
            runtime.step()
        self.assertEqual(memory.cells, {})
        self.assertEqual(runtime.pc, 0)
        self.assertNotIn(protocol.Opcode.RETIRE, runtime.sent)

    def test_an_access_outside_the_frame_is_refused_before_retire_is_sent(self):
        result_payload = (
            (1).to_bytes(4, "little") + (1).to_bytes(4, "little") + bytes(4)
            + bytes([0])
            + bytes([0])
            + bytes([1]) + (9).to_bytes(4, "little")
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
        with self.assertRaisesRegex(ProtocolViolation, "access to address 9"):
            runtime.step()
        self.assertNotIn(protocol.Opcode.RETIRE, runtime.sent)

    @staticmethod
    def _deferred_result(target: int, local: int) -> bytes:
        """A SET-shaped result carrying one deferred pair and one access to 2."""
        return (
            (1).to_bytes(4, "little") + (1).to_bytes(4, "little") + bytes(4)
            + bytes([0])
            + bytes([1]) + target.to_bytes(4, "little") + local.to_bytes(4, "little")
            + bytes([1]) + (2).to_bytes(4, "little")
        )

    def _deferred_runtime(self, target: int, local: int):
        memory = HostMemory(cells={2: 0xCAFE})
        runtime = self._ScriptedRuntime(
            program(set_slot(2, 1)),
            memory=memory,
            result_payload=self._deferred_result(target, local),
            retire_payload=(
                (1).to_bytes(4, "little") + (1).to_bytes(4, "little")
                + (1).to_bytes(4, "little") + bytes(4)
            ),
        )
        return memory, runtime

    def test_a_deferred_target_outside_the_frame_is_refused_before_retire_is_sent(self):
        # A deferred pair is a delayed write: resolve_deferred() closes it by
        # copying the known side onto the unknown one. Cell 2 is known and the
        # SET frame carried only address 2, so accepting (target=9, local=2)
        # would mint cell 9 in host memory from a cell the endpoint was never
        # shown alongside it.
        memory, runtime = self._deferred_runtime(9, 2)
        with self.assertRaisesRegex(ProtocolViolation, "target is address 9"):
            runtime.step()
        self.assertEqual(memory.cells, {2: 0xCAFE})
        self.assertEqual(memory.deferred, [])
        self.assertEqual(runtime.pc, 0)
        self.assertNotIn(protocol.Opcode.RETIRE, runtime.sent)

    def test_a_deferred_local_outside_the_frame_is_refused_before_retire_is_sent(self):
        # Both endpoints have to be in-frame, not just the target: the pair is
        # symmetric, so whichever side is unknown is the one that gets written.
        memory, runtime = self._deferred_runtime(2, 9)
        with self.assertRaisesRegex(ProtocolViolation, "local is address 9"):
            runtime.step()
        self.assertEqual(memory.cells, {2: 0xCAFE})
        self.assertEqual(memory.deferred, [])
        self.assertEqual(runtime.pc, 0)
        self.assertNotIn(protocol.Opcode.RETIRE, runtime.sent)

    def test_an_in_frame_deferred_pair_is_still_retired_and_recorded(self):
        """Guards the two tests above from passing because RETIRE never happens."""
        memory, runtime = self._deferred_runtime(2, 2)
        record = runtime.step()
        self.assertIn(protocol.Opcode.RETIRE, runtime.sent)
        self.assertIsNone(record.fault)
        self.assertEqual(record.deferred, [{"target": 2, "local": 2}])
        self.assertEqual(runtime.pc, 1)

    def test_every_real_endpoint_effect_stays_inside_the_frame(self):
        # The containment rule must not reject the endpoint it is written
        # against: drive the real endpoint and assert each opcode only ever
        # touches addresses its own request carried.
        runtime = HostRuntime(program(
            set_slot(2, 3),
            set_slot(3, 5),
            {"op": "Xor", "a": 2, "b": 3, "c": 4},
            {"op": "Mul", "a": 2, "b": 3, "c": 5},
        ))
        result = runtime.run()
        self.assertEqual(result.terminal, "halted")
        for record in result.records:
            frame = set(record.addresses)
            self.assertTrue({w["address"] for w in record.writes} <= frame)
            self.assertTrue(set(record.accesses) <= frame)
            self.assertEqual(record.deferred, [])

    def test_the_real_endpoint_defers_only_inside_the_frame(self):
        # Exercise the one DEREF_CELL quadrant that hands an equality back and
        # check the pair against the addresses the request itself names.
        fp, alpha, beta, gamma, base = 4, 1, 2, 3, 8
        endpoint = protocol.Lsc1Endpoint()

        def drive(frame):
            raw, _ = protocol.drive(endpoint, frame.encode())
            return protocol.decode_response(raw)

        profile = protocol.Profile.INTERPRETER_COMPAT
        self.assertIs(
            drive(protocol.build_negotiate(profile=profile)).status, protocol.Status.OK
        )
        reply = drive(protocol.build_deref(
            protocol.Opcode.DEREF_CELL,
            txn_id=1,
            pc=0,
            fp=fp,
            profile=profile,
            alpha=alpha,
            beta=beta,
            gamma=gamma,
            pointer=protocol.Cell(True, protocol.field_encode(base)),
            base=base,
            target=protocol.ABSENT,
            local=protocol.ABSENT,
        ))
        self.assertIs(reply.status, protocol.Status.OK)
        result = decode_result_payload(reply.payload, expected_txn_id=1)
        self.assertEqual(
            result["deferred"], [{"target": base + beta, "local": fp + gamma}]
        )
        in_frame = {fp + alpha, base + beta, fp + gamma}
        for item in result["deferred"]:
            self.assertIn(item["target"], in_frame)
            self.assertIn(item["local"], in_frame)

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

    class _RetireSpoofingRuntime(HostRuntime):
        """Lets the instruction succeed, then scripts the RETIRE answer."""

        def __init__(self, *args, retire_reply, **kwargs):
            self.retire_reply = retire_reply
            super().__init__(*args, **kwargs)

        def _exchange(self, frame):
            if protocol.Opcode(frame.opcode) is protocol.Opcode.RETIRE:
                return self.retire_reply
            return super()._exchange(frame)

    def _refuse_retire_fault(self, reply, message):
        runtime = self._RetireSpoofingRuntime(program(set_slot(2, 1)), retire_reply=reply)
        with self.assertRaisesRegex(ProtocolViolation, message):
            runtime.step()
        self.assertFalse(runtime.faulted)

    def test_a_non_retired_non_fault_status_is_not_recorded_as_a_fault(self):
        # Protocol 9.1: none of these bind the staged transaction, so recording
        # one as this step's fault would end the run with it still pending.
        for status in (protocol.Status.OK, protocol.Status.SERVICE_REQUIRED, protocol.Status.INFO):
            with self.subTest(status=status.name):
                self._refuse_retire_fault(
                    protocol.ResponseFrame(status, (1).to_bytes(4, "little") + bytes(1)),
                    f"retire answered {status.name}, which is not a fault status",
                )

    def test_a_retire_fault_payload_of_the_wrong_size_is_a_protocol_violation(self):
        for payload in (b"", (1).to_bytes(4, "little"), (1).to_bytes(4, "little") + bytes(2)):
            with self.subTest(length=len(payload)):
                self._refuse_retire_fault(
                    protocol.ResponseFrame(protocol.Status.BAD_CRC, payload),
                    f"retire fault payload has {len(payload)} bytes, expected 5",
                )

    def test_a_frame_level_retire_rejection_is_a_protocol_violation(self):
        # Frame-level faults echo txn_id 0: the endpoint never bound them to the
        # transaction, which therefore survives in RESULT_PENDING.
        for echoed in (0, 2, 9):
            with self.subTest(txn_id=echoed):
                self._refuse_retire_fault(
                    protocol.ResponseFrame(
                        protocol.Status.BAD_CRC,
                        echoed.to_bytes(4, "little") + bytes(1),
                    ),
                    f"retire fault echoed txn_id {echoed}, expected 1",
                )

    def test_a_non_discarding_retire_fault_binding_this_txn_is_still_refused(self):
        # Echoing the in-flight txn_id is not enough. At RETIRE the endpoint is
        # holding a decided transition, and 9.1 discards it only on
        # RETIRE_MISMATCH; every one of these would leave it RESULT_PENDING, so
        # ending the run on one strands it.
        for status in (
            protocol.Status.BAD_SOF,
            protocol.Status.BAD_VERSION,
            protocol.Status.BAD_OPCODE,
            protocol.Status.BAD_LENGTH,
            protocol.Status.BAD_CRC,
            protocol.Status.BAD_FLAGS,
            protocol.Status.BAD_PROFILE,
            protocol.Status.BAD_STATE,
            protocol.Status.BAD_SERVICE,
            protocol.Status.STATE_MISMATCH,
            protocol.Status.INDEX_RANGE,
            protocol.Status.WRITE_CONFLICT,
        ):
            with self.subTest(status=status.name):
                self._refuse_retire_fault(
                    protocol.ResponseFrame(
                        status, (1).to_bytes(4, "little") + bytes([1])
                    ),
                    f"retire answered {status.name}, which does not discard the "
                    "staged transition under section 9.1",
                )

    def test_a_frame_only_instruction_fault_binding_this_txn_is_still_refused(self):
        # These decided nothing about the transition: the framing faults never
        # reached a handler, and BAD_STATE means the endpoint is holding a
        # transaction the host does not know about.
        for status in (
            protocol.Status.BAD_SOF,
            protocol.Status.BAD_VERSION,
            protocol.Status.BAD_OPCODE,
            protocol.Status.BAD_LENGTH,
            protocol.Status.BAD_CRC,
            protocol.Status.BAD_FLAGS,
            protocol.Status.BAD_STATE,
            protocol.Status.BAD_SERVICE,
        ):
            with self.subTest(status=status.name):
                self._refuse_fault(
                    protocol.ResponseFrame(
                        status, (1).to_bytes(4, "little") + bytes([1])
                    ),
                    f"instruction answered {status.name}, a section 9.1 "
                    "frame-level rejection that decided nothing",
                )

    def test_an_idle_guard_fault_is_still_attributed_to_the_step(self):
        # 9.1 reaches these only after the endpoint confirmed it is IDLE, so
        # nothing is outstanding behind them and they are genuine refusals.
        for status in (
            protocol.Status.BAD_PROFILE,
            protocol.Status.STATE_MISMATCH,
            protocol.Status.INDEX_RANGE,
        ):
            with self.subTest(status=status.name):
                runtime = self._FaultingRuntime(
                    program(set_slot(2, 1)),
                    fault_reply=protocol.ResponseFrame(
                        status, (1).to_bytes(4, "little") + bytes([1])
                    ),
                )
                self.assertEqual(runtime.step().fault, status.name)
                self.assertTrue(runtime.faulted)

    def test_a_duplicate_retire_against_the_real_endpoint_is_refused(self):
        # Protocol 10.1: a second RETIRE finds IDLE and is BAD_STATE, echoing the
        # requested txn_id in a well-formed 8.6 payload. This is the unspoofed
        # path that reaches the frame-only class with a matching transaction.
        endpoint = protocol.Lsc1Endpoint()
        runtime = HostRuntime(program(set_slot(2, 1)), endpoint=endpoint)
        replayed = []

        original = runtime._exchange

        def replaying(frame):
            reply = original(frame)
            if protocol.Opcode(frame.opcode) is protocol.Opcode.RETIRE:
                replayed.append(reply)
                return original(frame)
            return reply

        runtime._exchange = replaying
        with self.assertRaisesRegex(ProtocolViolation, "BAD_STATE"):
            runtime.step()
        self.assertEqual([reply.status for reply in replayed], [protocol.Status.RETIRED])
        self.assertFalse(runtime.faulted)

    def test_a_well_formed_retire_fault_is_still_attributed_to_the_step(self):
        # RETIRE_MISMATCH discards the transaction (9.1), so it is a real outcome.
        runtime = self._RetireSpoofingRuntime(
            program(set_slot(2, 1)),
            retire_reply=protocol.ResponseFrame(
                protocol.Status.RETIRE_MISMATCH,
                (1).to_bytes(4, "little") + bytes([1]),
            ),
        )
        record = runtime.step()
        self.assertEqual(record.fault, "RETIRE_MISMATCH")
        self.assertTrue(runtime.faulted)

    def test_an_overflowing_effective_address_is_a_fault_terminal(self):
        cases = {
            "set": (set_slot(1, 5), 0xFFFFFFFF),
            "set_far_offset": (set_slot(0xFFFFFFFF, 5), 1),
            "binary_a": ({"op": "Xor", "a": 1, "b": 0, "c": 0}, 0xFFFFFFFF),
            "binary_c": ({"op": "Mul", "a": 0, "b": 0, "c": 2}, 0xFFFFFFFE),
        }
        for name, (slot, fp0) in cases.items():
            with self.subTest(case=name):
                runtime = HostRuntime(program(slot, fp0=fp0))
                result = runtime.run()
                self.assertEqual(result.terminal, "fault")
                self.assertIn("u32_overflow", result.reason)
                self.assertTrue(runtime.faulted)
                self.assertEqual(result.records, [])

    class _CorruptingLaneRuntime(HostRuntime):
        """Corrupts the raw bytes of one chosen response, deterministically.

        Counts post-NEGOTIATE exchanges: 1 is the instruction response, 2 the
        RETIRE response.
        """

        def __init__(self, *args, corrupt_at, mangle, **kwargs):
            self.exchanges = 0
            self.corrupt_at = corrupt_at
            self.mangle = mangle
            super().__init__(*args, **kwargs)

        def _exchange(self, frame):
            if protocol.Opcode(frame.opcode) is protocol.Opcode.NEGOTIATE:
                return super()._exchange(frame)
            self.exchanges += 1
            raw, cycles = protocol.drive(self.endpoint, frame.encode())
            self.lane_cycles += cycles
            if self.exchanges == self.corrupt_at:
                raw = self.mangle(bytearray(raw))
            return protocol.decode_response(bytes(raw))

    def test_a_corrupted_response_is_not_reported_as_a_preparation_fault(self):
        # `decode_response` signals with the same ProtocolFault type as
        # `checked_add`. A frame that fails to decode arrives *after* the
        # request was sent, so the endpoint may hold a pending or an already
        # committed transaction: it must not be turned into a fault terminal.
        def flip_crc(raw):
            raw[-1] ^= 0xFF
            return raw

        def flip_sof(raw):
            raw[0] ^= 0xFF
            return raw

        def truncate(raw):
            return raw[:-3]

        expected = {
            "flip_crc": protocol.Status.BAD_CRC,
            "flip_sof": protocol.Status.BAD_SOF,
            "truncate": protocol.Status.BAD_LENGTH,
        }
        for name, mangle in (("flip_crc", flip_crc), ("flip_sof", flip_sof), ("truncate", truncate)):
            for corrupt_at, where in ((1, "instruction"), (2, "retire")):
                with self.subTest(corruption=name, response=where):
                    runtime = self._CorruptingLaneRuntime(
                        program(set_slot(2, 1)), corrupt_at=corrupt_at, mangle=mangle
                    )
                    with self.assertRaises(protocol.ProtocolFault) as caught:
                        runtime.run()
                    self.assertIs(caught.exception.status, expected[name])
                    self.assertFalse(runtime.faulted)

    def test_a_non_overflowing_address_is_not_a_preparation_fault(self):
        # The catch must be exactly `checked_add`, not "anything near the top of
        # u32": fp+offset == U32_MAX adds fine, so it reaches the endpoint and
        # comes back as an ordinary fault frame with a step record behind it.
        runtime = HostRuntime(program(set_slot(1, 5), fp0=0xFFFFFFFE))
        result = runtime.run()
        self.assertEqual(result.terminal, "fault")
        self.assertNotIn("preparing the transaction", result.reason)
        self.assertEqual([record.addresses for record in result.records], [[0xFFFFFFFF]])
        self.assertEqual(result.records[0].fault, "INDEX_RANGE")

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
            "status", "fault", "retire_seq", "lane_cycles", "lane_bytes", "service",
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

    def test_blake3_service_completes_a_real_multi_transaction_workload(self):
        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = HostRuntime(
            program(*(set_slot(index, index - 1) for index in range(2, 8)), slot),
            session_epoch=0x1122334455667788,
        )
        result = runtime.run()
        self.assertEqual(result.terminal, "halted")
        self.assertEqual(len(result.records), 7)
        self.assertEqual([record.retire_seq for record in result.records], list(range(1, 8)))
        service = result.records[-1].service
        self.assertEqual(service, {
            "schema": "leansilicon.host.blake3-service/1",
            "session_epoch": "1122334455667788",
            "txn_id": 7,
            "service_id": 1,
            "kind": 1,
            "request_sha256": "e9a3ad0c73466f8abbb7d6c126288b2432efd80c5ebe20dde0ba97be6c71d291",
            "response_sha256": "7f2015db62c1378f278100fb314c47e22f99a949e8892c714dc1e91b4df4740c",
        })
        self.assertEqual(runtime.memory.read(8), 0xB59E830F1B4CA1A10472453345BE3E66)
        self.assertEqual(runtime.memory.read(9), 0x8A3B1295ADFC65C8E35949C82DC5BBE3)

    def test_blake3_service_mutation_changes_the_bound_payload_and_writes(self):
        class MutatedService:
            def compress(self, request):
                from host.blake3_service import compress
                digest = bytearray(compress(request))
                digest[0] ^= 1
                return bytes(digest)

        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = HostRuntime(
            program(*(set_slot(index, index - 1) for index in range(2, 8)), slot),
            blake3_service=MutatedService(), session_epoch=0x1122334455667788,
        )
        result = runtime.run()
        self.assertEqual(result.terminal, "halted")
        self.assertNotEqual(
            result.records[-1].service["response_sha256"],
            "7f2015db62c1378f278100fb314c47e22f99a949e8892c714dc1e91b4df4740c",
        )
        self.assertEqual(runtime.memory.read(8), 0xB59E830F1B4CA1A10472453345BE3E67)

    def test_falsey_caller_supplied_blake3_service_is_preserved(self):
        class FalseyService:
            called = False

            def __bool__(self):
                return False

            def compress(self, request):
                self.called = True
                from host.blake3_service import compress
                return compress(request)

        service = FalseyService()
        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = HostRuntime(
            program(*(set_slot(index, index - 1) for index in range(2, 8)), slot),
            blake3_service=service, session_epoch=1,
        )
        self.assertEqual(runtime.run().terminal, "halted")
        self.assertIs(runtime.blake3_service, service)
        self.assertTrue(service.called)

    def test_blake3_metadata_is_rejected_before_the_endpoint_is_staged(self):
        for metadata in (65 << 64, 0x80 << 96):
            with self.subTest(metadata=metadata):
                slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                        "metadata": f"{metadata:#034x}"}
                runtime = HostRuntime(program(slot), session_epoch=1)
                result = runtime.run()
                self.assertEqual(result.terminal, "fault")
                self.assertIn("bad_service preparing", result.reason)
                self.assertEqual(runtime.endpoint.state.name, "IDLE")
                self.assertEqual(runtime.endpoint.abort_count, 0)
                self.assertIsNone(runtime.service_adapter.outstanding)

    def test_blake3_requires_service_required_and_aborts_an_unexpected_reply(self):
        class WrongStatusRuntime(HostRuntime):
            def _exchange(self, frame):
                reply = super()._exchange(frame)
                if protocol.Opcode(frame.opcode) is protocol.Opcode.BLAKE3_REQUEST:
                    return protocol.ResponseFrame(protocol.Status.OK, reply.payload)
                return reply

        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = WrongStatusRuntime(program(slot), session_epoch=1)
        with self.assertRaisesRegex(ProtocolViolation, "must suspend with SERVICE_REQUIRED"):
            runtime.step()
        self.assertEqual(runtime.endpoint.state.name, "IDLE")
        self.assertEqual(runtime.endpoint.abort_count, 1)
        self.assertIsNone(runtime.service_adapter.outstanding)

    def test_exhausted_blake3_service_retries_abort_and_leave_runtime_reusable(self):
        class UnavailableService:
            def compress(self, request):
                raise ServiceInfrastructureError("unavailable")

        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = HostRuntime(
            program(slot), blake3_service=UnavailableService(), session_epoch=1,
        )
        with self.assertRaisesRegex(ServiceInfrastructureError, "unavailable"):
            runtime.step()
        self.assertEqual(runtime.endpoint.state.name, "IDLE")
        self.assertEqual(runtime.endpoint.abort_count, 1)
        self.assertIsNone(runtime.service_adapter.outstanding)

        from host.blake3_service import SoftwareBlake3HostService
        runtime.blake3_service = SoftwareBlake3HostService()
        self.assertEqual(runtime.step().status, protocol.Status.OK.name)

    def test_unexpected_blake3_callback_failure_aborts_and_leaves_runtime_reusable(self):
        class BrokenService:
            def compress(self, request):
                raise RuntimeError("backend bug")

        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = HostRuntime(
            program(slot), blake3_service=BrokenService(), session_epoch=1,
        )
        with self.assertRaisesRegex(RuntimeError, "backend bug"):
            runtime.step()
        self.assertEqual(runtime.endpoint.state.name, "IDLE")
        self.assertEqual(runtime.endpoint.abort_count, 1)
        self.assertIsNone(runtime.service_adapter.outstanding)

        from host.blake3_service import SoftwareBlake3HostService
        runtime.blake3_service = SoftwareBlake3HostService()
        self.assertEqual(runtime.step().status, protocol.Status.OK.name)

    def test_blake3_service_required_must_match_the_in_flight_transaction(self):
        class WrongTransactionRuntime(HostRuntime):
            corrupt_service_key = True

            def _exchange(self, frame):
                reply = super()._exchange(frame)
                if (self.corrupt_service_key
                        and protocol.Opcode(frame.opcode) is protocol.Opcode.BLAKE3_REQUEST):
                    payload = bytearray(reply.payload)
                    payload[0:4] = (self.txn_id + 1).to_bytes(4, "little")
                    return protocol.ResponseFrame(reply.status, bytes(payload))
                return reply

        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = WrongTransactionRuntime(program(slot), session_epoch=1)
        with self.assertRaisesRegex(ServiceSemanticError, "does not match in-flight"):
            runtime.step()
        self.assertEqual(runtime.endpoint.state.name, "IDLE")
        self.assertEqual(runtime.endpoint.abort_count, 1)
        self.assertIsNone(runtime.service_adapter.outstanding)

        runtime.corrupt_service_key = False
        self.assertEqual(runtime.step().status, protocol.Status.OK.name)

    def test_blake3_service_required_must_match_the_prepared_operands(self):
        class WrongOperandsRuntime(HostRuntime):
            corrupt_service_operands = True

            def _exchange(self, frame):
                reply = super()._exchange(frame)
                if (self.corrupt_service_operands
                        and protocol.Opcode(frame.opcode) is protocol.Opcode.BLAKE3_REQUEST):
                    payload = bytearray(reply.payload)
                    payload[10] ^= 1
                    return protocol.ResponseFrame(reply.status, bytes(payload))
                return reply

        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = WrongOperandsRuntime(program(slot), session_epoch=1)
        with self.assertRaisesRegex(ServiceSemanticError, "prepared BLAKE3_REQUEST"):
            runtime.step()
        self.assertEqual(runtime.endpoint.state.name, "IDLE")
        self.assertEqual(runtime.endpoint.abort_count, 1)
        self.assertIsNone(runtime.service_adapter.outstanding)

        runtime.corrupt_service_operands = False
        self.assertEqual(runtime.step().status, protocol.Status.OK.name)

    def test_wrong_type_blake3_digest_aborts_and_leaves_runtime_reusable(self):
        class WrongTypeService:
            def compress(self, request):
                return "x" * 32

        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = HostRuntime(
            program(slot), blake3_service=WrongTypeService(), session_epoch=1,
        )
        with self.assertRaisesRegex(ServiceSemanticError, "non-bytes"):
            runtime.step()
        self.assertEqual(runtime.endpoint.state.name, "IDLE")
        self.assertEqual(runtime.endpoint.abort_count, 1)
        self.assertIsNone(runtime.service_adapter.outstanding)

        from host.blake3_service import SoftwareBlake3HostService
        runtime.blake3_service = SoftwareBlake3HostService()
        self.assertEqual(runtime.step().status, protocol.Status.OK.name)

    def test_blake3_service_response_exchange_failure_aborts_and_is_reusable(self):
        class FailingResponseExchangeRuntime(HostRuntime):
            fail_response_exchange = True

            def _exchange(self, frame):
                if (self.fail_response_exchange
                        and protocol.Opcode(frame.opcode) is protocol.Opcode.SERVICE_RESPONSE):
                    raise TimeoutError("service response timeout")
                return super()._exchange(frame)

        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = FailingResponseExchangeRuntime(program(slot), session_epoch=1)
        with self.assertRaisesRegex(TimeoutError, "service response timeout"):
            runtime.step()
        self.assertEqual(runtime.endpoint.state.name, "IDLE")
        self.assertEqual(runtime.endpoint.abort_count, 1)
        self.assertIsNone(runtime.service_adapter.outstanding)

        runtime.fail_response_exchange = False
        self.assertEqual(runtime.step().status, protocol.Status.OK.name)

    def test_rejected_blake3_service_response_aborts_and_is_reusable(self):
        class RejectedResponseRuntime(HostRuntime):
            corrupt_response = True

            def _exchange(self, frame):
                if (self.corrupt_response
                        and protocol.Opcode(frame.opcode) is protocol.Opcode.SERVICE_RESPONSE):
                    payload = bytearray(frame.payload)
                    payload[0:4] = (self.txn_id + 1).to_bytes(4, "little")
                    frame = protocol.RequestFrame(frame.opcode, bytes(payload))
                return super()._exchange(frame)

        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = RejectedResponseRuntime(program(slot), session_epoch=1)
        with self.assertRaisesRegex(ProtocolViolation, "fault echoed txn_id"):
            runtime.step()
        self.assertEqual(runtime.endpoint.state.name, "IDLE")
        self.assertEqual(runtime.endpoint.abort_count, 1)
        self.assertIsNone(runtime.service_adapter.outstanding)

        runtime.corrupt_response = False
        self.assertEqual(runtime.step().status, protocol.Status.OK.name)

    def test_initial_blake3_exchange_failure_aborts_and_is_reusable(self):
        class FailingRequestExchangeRuntime(HostRuntime):
            fail_request_exchange = True

            def _exchange(self, frame):
                reply = super()._exchange(frame)
                if (self.fail_request_exchange
                        and protocol.Opcode(frame.opcode) is protocol.Opcode.BLAKE3_REQUEST):
                    raise TimeoutError("service required timeout")
                return reply

        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = FailingRequestExchangeRuntime(program(slot), session_epoch=1)
        with self.assertRaisesRegex(TimeoutError, "service required timeout"):
            runtime.step()
        self.assertEqual(runtime.endpoint.state.name, "IDLE")
        self.assertEqual(runtime.endpoint.abort_count, 1)
        self.assertIsNone(runtime.service_adapter.outstanding)

        runtime.fail_request_exchange = False
        self.assertEqual(runtime.step().status, protocol.Status.OK.name)

    def test_malformed_blake3_result_aborts_and_is_reusable(self):
        class MalformedResultRuntime(HostRuntime):
            corrupt_result = True

            def _exchange(self, frame):
                reply = super()._exchange(frame)
                if (self.corrupt_result
                        and protocol.Opcode(frame.opcode) is protocol.Opcode.SERVICE_RESPONSE
                        and reply.status is protocol.Status.OK):
                    return protocol.ResponseFrame(reply.status, reply.payload[:-1])
                return reply

        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = MalformedResultRuntime(program(slot), session_epoch=1)
        with self.assertRaisesRegex(ProtocolViolation, "truncated"):
            runtime.step()
        self.assertEqual(runtime.endpoint.state.name, "IDLE")
        self.assertEqual(runtime.endpoint.abort_count, 1)
        self.assertIsNone(runtime.service_adapter.outstanding)

        runtime.corrupt_result = False
        self.assertEqual(runtime.step().status, protocol.Status.OK.name)

    def test_rejected_blake3_digest_clears_binding_for_a_reusable_runtime(self):
        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = HostRuntime(
            program(*(set_slot(index, index - 1) for index in range(2, 10)), slot),
            session_epoch=1,
        )
        result = runtime.run()
        self.assertEqual(result.terminal, "fault")
        self.assertEqual(result.records[-1].fault, "WRITE_CONFLICT")
        self.assertIsNone(runtime.service_adapter.outstanding)

        retried = runtime.step()
        self.assertEqual(retried.fault, "WRITE_CONFLICT")
        self.assertIsNone(runtime.service_adapter.outstanding)

    def test_rejected_blake3_retire_clears_binding_after_endpoint_discard(self):
        class WrongRetireRuntime(HostRuntime):
            reject_next_retire = False

            def _exchange(self, frame):
                opcode = protocol.Opcode(frame.opcode)
                if opcode is protocol.Opcode.SERVICE_RESPONSE:
                    self.reject_next_retire = True
                elif opcode is protocol.Opcode.RETIRE and self.reject_next_retire:
                    frame = protocol.build_retire(
                        txn_id=int.from_bytes(frame.payload[:4], "little"),
                        result_crc=int.from_bytes(frame.payload[4:8], "little") ^ 1,
                    )
                return super()._exchange(frame)

        slot = {"op": "Blake3", "ins": [2, 3, 4, 5], "cv": 6, "out": 8,
                "metadata": f"{64 << 64:#034x}"}
        runtime = WrongRetireRuntime(
            program(*(set_slot(index, index - 1) for index in range(2, 8)), slot),
            session_epoch=1,
        )
        result = runtime.run()
        self.assertEqual(result.terminal, "fault")
        self.assertEqual(result.records[-1].fault, "RETIRE_MISMATCH")
        self.assertEqual(runtime.endpoint.state.name, "IDLE")
        self.assertIsNone(runtime.service_adapter.outstanding)

    def test_deref_modes_are_prepared_with_host_pointer_resolution(self):
        expectations = {
            "Cell": 0x55,
            "Pc": protocol.field_encode(2),
            "Fp": protocol.field_encode(0),
        }
        for mode, expected in expectations.items():
            with self.subTest(mode=mode):
                memory = HostMemory(cells={
                    0: 1, 1: 0, 2: protocol.field_encode(8), 3: 0x55,
                })
                runtime = HostRuntime(program({
                    "op": "Deref", "alpha": 2, "beta": 1,
                    "gamma": 3, "mode": mode,
                }), memory=memory)
                result = runtime.run()
                self.assertEqual(result.terminal, "halted")
                self.assertEqual(runtime.memory.read(9), expected)
                self.assertEqual(result.records[0].accesses, [2, 9, 3])

    def test_jump_taken_and_not_taken_are_host_proposed_and_verified(self):
        taken_memory = HostMemory(cells={
            0: 1, 1: 0, 2: 1,
            3: protocol.field_encode(1), 4: protocol.field_encode(0),
        })
        taken = HostRuntime(
            program({"op": "Jump", "oc": 2, "od": 3, "of": 4}),
            memory=taken_memory,
        )
        taken_result = taken.run()
        self.assertEqual(taken_result.terminal, "halted")
        self.assertEqual((taken.pc, taken.fp), (1, 0))
        self.assertEqual(taken_result.records[0].branch, {
            "taken": True, "dest_pc": 1, "dest_fp": 0,
        })

        not_taken = HostRuntime(program({"op": "Jump", "oc": 2, "od": 3, "of": 4}))
        not_taken_result = not_taken.run()
        self.assertEqual(not_taken_result.terminal, "halted")
        self.assertEqual((not_taken.pc, not_taken.fp), (1, 0))
        self.assertEqual(not_taken_result.records[0].branch, {
            "taken": False, "dest_pc": 0, "dest_fp": 0,
        })

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
        self.assertEqual(result.terminal, "halted")

        mem = [int(value, 16) for value in self.upstream["mem"]]
        self.assertEqual(len(mem), self.upstream["mem_used"])
        self.assertTrue(runtime.memory.cells)
        for address, value in sorted(runtime.memory.cells.items()):
            with self.subTest(address=address):
                self.assertLess(address, self.upstream["mem_used"])
                self.assertEqual(value, mem[address])

    def test_complete_program_is_a_full_match(self):
        runtime = HostRuntime(self.program, memory=HostMemory.with_public_input(1, 0))
        result = runtime.run()
        comparison = compare(runtime, result, self.upstream)
        self.assertEqual(result.terminal, "halted")
        self.assertEqual(comparison["result"], "MATCH")
        self.assertNotIn("unsupported_suffix", comparison["not_compared"])

    def test_the_host_covers_every_cell_the_frozen_run_touched(self):
        runtime = HostRuntime(self.program, memory=HostMemory.with_public_input(1, 0))
        runtime.run()
        self.assertEqual(sorted(runtime.memory.cells), list(range(self.upstream["mem_used"])))

    def test_complete_program_cycles_match_the_frozen_run(self):
        runtime = HostRuntime(self.program, memory=HostMemory.with_public_input(1, 0))
        result = runtime.run()
        self.assertEqual(result.terminal, "halted")
        self.assertEqual(runtime.step_index, self.upstream["cycles"])

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
            "host omitted a nonzero upstream cell",
            comparison["mismatches"][-1]["reason"],
        )

    def test_halted_sparse_memory_treats_unwritten_cells_as_zero(self):
        runtime = SimpleNamespace(
            memory=HostMemory(cells={10: 0xAB}),
            step_index=1,
        )
        run = SimpleNamespace(terminal="halted", reason="")
        upstream = {
            "cycles": 1,
            "mem_used": 11,
            "mem": [f"{0:#034x}" for _ in range(10)] + [f"{0xAB:#034x}"],
        }
        result = compare(runtime, run, upstream)
        self.assertEqual(result["result"], "MATCH")
        self.assertEqual(result["mismatches"], [])

    def test_live_probe_must_reproduce_recorded_execution(self):
        artifact = json.loads(ARTIFACT.read_text())
        probe = {
            "pc0": artifact["program"]["pc0"],
            "fp0": artifact["program"]["fp0"],
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

    def test_live_probe_must_reproduce_recorded_entry_metadata(self):
        artifact = json.loads(ARTIFACT.read_text())
        probe = {
            "pc0": artifact["program"]["pc0"],
            "fp0": artifact["program"]["fp0"],
            "bytecode": artifact["program"]["bytecode"],
            "execution": dict(artifact["upstream_execution"]),
        }
        artifact["program"]["fp0"] += 1
        with (
            mock.patch.object(comparison_tool._export, "candidate_head"),
            mock.patch.object(comparison_tool._export, "require_checkout"),
            mock.patch.object(
                comparison_tool._export,
                "run_probe",
                return_value=(probe, ["cargo", "run"]),
            ),
        ):
            with self.assertRaisesRegex(SystemExit, "recorded entry metadata: fp0"):
                comparison_tool.upstream_execution(ARTIFACT, artifact, ROOT, "1.88.0")

    def test_compiler_probe_worktree_disables_post_checkout_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory) / "upstream"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            tracked = repo / "compiler.rs"
            tracked.write_text("const TRUSTED: bool = true;\n")
            subprocess.run(["git", "add", "compiler.rs"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "captured"], cwd=repo, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            hook = repo / ".git" / "hooks" / "post-checkout"
            hook.write_text(
                "#!/bin/sh\n"
                "printf 'const TRUSTED: bool = false;\\n' > compiler.rs\n"
                "git update-index --assume-unchanged compiler.rs\n"
            )
            hook.chmod(0o755)
            worktree = pathlib.Path(directory) / "probe"

            comparison_tool._export.add_verified_worktree(repo, worktree, head)
            try:
                self.assertEqual(
                    (worktree / "compiler.rs").read_text(),
                    "const TRUSTED: bool = true;\n",
                )
                probe = worktree / "probe.rs"
                probe.write_text("fn main() {}\n")
                comparison_tool._export.set_worktree_writable(
                    worktree, writable=False
                )
                self.assertEqual((worktree / "compiler.rs").stat().st_mode & 0o222, 0)
                self.assertEqual(probe.stat().st_mode & 0o222, 0)
                comparison_tool._export.require_actual_tracked_bytes(
                    worktree, frozenset({"probe.rs"})
                )
            finally:
                comparison_tool._export.set_worktree_writable(
                    worktree, writable=True
                )
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(worktree)],
                    cwd=repo,
                    check=True,
                )

    def test_compiler_probe_rejects_smudge_created_cargo_config(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory) / "upstream"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            subprocess.run(
                ["git", "config", "filter.inject.clean", "cat"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                [
                    "git", "config", "filter.inject.smudge",
                    "mkdir -p .cargo && printf '[build]\\nrustc-wrapper=\"evil\"\\n' "
                    "> .cargo/config.toml && cat",
                ],
                cwd=repo,
                check=True,
            )
            (repo / ".gitignore").write_text(".cargo/\n")
            (repo / ".gitattributes").write_text("compiler.rs filter=inject\n")
            (repo / "compiler.rs").write_text("const TRUSTED: bool = true;\n")
            subprocess.run(
                ["git", "add", ".gitignore", ".gitattributes", "compiler.rs"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "commit", "-qm", "captured"], cwd=repo, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            worktree = pathlib.Path(directory) / "probe"

            with self.assertRaisesRegex(SystemExit, "extra paths"):
                comparison_tool._export.add_verified_worktree(repo, worktree, head)

    def test_compiler_probe_executes_from_namespace_private_archive(self):
        if not comparison_tool._export.private_namespace_available():
            self.skipTest("runner forbids the privileged mount broker required by the lane")
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            repo = base / "upstream"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            (repo / "README").write_text("canonical archive\n")
            subprocess.run(["git", "add", "README"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "captured"], cwd=repo, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            fake_bin = base / "bin"
            fake_bin.mkdir()
            cargo = fake_bin / "cargo"
            cargo.write_text(
                "#!/bin/sh\n"
                "test -f crates/lean_compiler/examples/leansilicon_export.rs\n"
                "printf '{\"private_archive\":true,\"uid\":%s}\\n' \"$(id -u)\"\n"
            )
            cargo.chmod(0o755)
            marker = base / "privileged-path-was-used"
            fake_shell = fake_bin / "sh"
            fake_shell.write_text(
                f"#!/bin/sh\ntouch {marker}\nexec /bin/sh \"$@\"\n"
            )
            fake_shell.chmod(0o755)
            fake_git = fake_bin / "git"
            fake_git.write_text(
                f"#!/bin/sh\ntouch {marker}\nexit 99\n"
            )
            fake_git.chmod(0o755)

            with mock.patch.dict(
                os.environ, {"PATH": f"{fake_bin}:{os.environ['PATH']}"}
            ), mock.patch.object(
                comparison_tool._export,
                "resolved_toolchain_snapshot",
                return_value=(fake_bin, "cargo"),
            ):
                try:
                    result, command = comparison_tool._export.run_probe(
                        repo, "source input", "test-toolchain", head
                    )
                except SystemExit as error:
                    if "dedicated read-only filesystem mount" in str(error):
                        self.skipTest(
                            "fake toolchain is not on a dedicated read-only mount"
                        )
                    raise

            self.assertTrue(result["private_archive"])
            self.assertGreaterEqual(result["uid"], 200000)
            self.assertNotEqual(result["uid"], 65534)
            self.assertEqual(command[0:2], ["cargo", "+test-toolchain"])
            self.assertFalse(marker.exists())

    def test_only_selected_rustup_toolchain_is_resolved_for_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "toolchains" / "1.88.0-target"
            (root / "bin").mkdir(parents=True)
            actual_cargo = root / "bin" / "cargo"
            actual_cargo.touch()
            proxy_bin = pathlib.Path(directory) / "proxy-bin"
            proxy_bin.mkdir()
            (proxy_bin / "cargo").touch()
            (proxy_bin / "rustup").touch()
            with (
                mock.patch.object(
                    comparison_tool._export.shutil,
                    "which",
                    return_value=str(proxy_bin / "cargo"),
                ),
                mock.patch.object(
                    comparison_tool._export.subprocess,
                    "check_output",
                    return_value=str(actual_cargo),
                ),
            ):
                selected_root, relative = (
                    comparison_tool._export.resolved_toolchain_snapshot("1.88.0")
                )

            self.assertEqual(selected_root, root)
            self.assertEqual(relative, "bin/cargo")

    def test_privileged_archive_rejects_symlink_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            (repo / "redirect").symlink_to("/tmp")
            subprocess.run(["git", "add", "redirect"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "symlink"], cwd=repo, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            (repo / "redirect").unlink()
            (repo / "redirect").write_text("replacement hides unsafe entry\n")
            subprocess.run(["git", "add", "redirect"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "replacement"], cwd=repo, check=True
            )
            replacement = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            subprocess.run(
                ["git", "replace", head, replacement], cwd=repo, check=True
            )

            with self.assertRaisesRegex(SystemExit, "unsafe entry.*redirect"):
                comparison_tool._export.require_safe_archive_tree(repo, head)

    def test_open_toolchain_snapshot_survives_mutable_parent_path_swap(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = pathlib.Path(directory) / "toolchains"
            selected = parent / "selected"
            (selected / "bin").mkdir(parents=True)
            (selected / "bin" / "cargo").write_text("selected")

            with mock.patch.object(
                comparison_tool._export,
                "resolved_toolchain_snapshot",
                return_value=(selected, "bin/cargo"),
            ):
                descriptor, relative = (
                    comparison_tool._export.open_resolved_toolchain_snapshot("1.88.0")
                )

            try:
                original = parent / "original"
                selected.rename(original)
                (selected / "bin").mkdir(parents=True)
                (selected / "bin" / "cargo").write_text("forged")

                pinned = pathlib.Path(f"/proc/self/fd/{descriptor}")
                self.assertTrue(os.path.samefile(pinned, original))
                self.assertEqual((pinned / relative).read_text(), "selected")
            finally:
                os.close(descriptor)

    def test_mutable_host_toolchain_mount_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with self.assertRaisesRegex(
                    SystemExit, "dedicated read-only filesystem mount"
                ):
                    comparison_tool._export.require_readonly_toolchain_mount(
                        descriptor
                    )
            finally:
                os.close(descriptor)

    def test_toolchain_manifest_authenticates_all_consumed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "bin").mkdir()
            cargo = root / "bin" / "cargo"
            cargo.write_bytes(b"canonical cargo")
            expected = comparison_tool._export.toolchain_tree_sha256(root)
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                comparison_tool._export.require_authenticated_toolchain(
                    descriptor, expected
                )
                cargo.write_bytes(b"forged cargo")
                with self.assertRaisesRegex(SystemExit, "identity mismatch"):
                    comparison_tool._export.require_authenticated_toolchain(
                        descriptor, expected
                    )
            finally:
                os.close(descriptor)

    def test_live_probe_rejects_non_x86_64_hosts_before_privilege(self):
        with mock.patch.object(
            comparison_tool._export.platform, "machine", return_value="aarch64"
        ), mock.patch.object(
            comparison_tool._export, "private_namespace_available"
        ) as namespace_available:
            with self.assertRaisesRegex(SystemExit, "requires x86_64 Linux"):
                comparison_tool._export.run_probe(
                    pathlib.Path("unused"), "source", "toolchain"
                )
        namespace_available.assert_not_called()

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

    def test_comparison_receipt_can_be_consumed_from_stdout_pipe(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                str(ROOT / "tools" / "host_upstream_comparison.py"),
                "--artifact",
                str(ARTIFACT),
                "--out",
                "-",
            ],
            text=True,
            capture_output=True,
        )
        receipt = json.loads(completed.stdout)
        self.assertEqual(receipt["schema"], comparison_tool.SCHEMA)
        self.assertIn(receipt["comparison"]["result"], {"MATCH", "MISMATCH"})


if __name__ == "__main__":
    unittest.main()

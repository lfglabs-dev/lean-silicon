#!/usr/bin/env python3
"""Deterministically generate the reviewed LSC-1 conformance corpus."""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim"))
import lsc1_transaction as lsc1  # noqa: E402

OUTPUT = ROOT / "conformance/corpus-v2.json"
UPSTREAM_COMMIT = "c308034ab78619b39a59d26f3dc60e7df5b52649"
P = lsc1.Profile.INTERPRETER_COMPAT
A = lsc1.ABSENT
C = lsc1.Cell

UPSTREAM_EXPECTED = {
    "scalar.set.forward": (1, 3, [5, 6, 0x1234]),
    "scalar.xor.forward": (1, 3, [0xDEAD, 0xBEEF, 0x6042]),
    "scalar.mul.forward": (1, 3, [0x53, 0xCA, 0x3F7E]),
    "scalar.xor.backsolve_a": (1, 3, [0x1111, 0x3333, 0x2222]),
    "scalar.xor.backsolve_b": (1, 3, [0x1111, 0x3333, 0x2222]),
    "scalar.deref.cell": (1, 9, [0x100, 0x77, 0, 0, 0, 0, 0, 0, 0x77]),
    "scalar.deref.pc": (1, 9, [0x100, 0, 0, 0, 0, 0, 0, 0, 4]),
    "scalar.deref.fp": (6, 12, [0, 0, 0, 0, 0x100, 1, 0x80, 1, 0x10, 0, 0, 0]),
    "scalar.jump.not_taken": (1, 2, [1, 0]),
    "scalar.jump.taken_nontrivial_inverse": (2, 4, [0x53, 8, 1, 0]),
}

UPSTREAM_TRANSITIONS = {
    "scalar.set.forward": (1, 0, [(2, 0x1234)]),
    "scalar.xor.forward": (1, 0, [(2, 0x6042)]),
    "scalar.mul.forward": (1, 0, [(2, 0x3F7E)]),
    "scalar.xor.backsolve_a": (1, 0, [(2, 0x2222)]),
    "scalar.xor.backsolve_b": (1, 0, [(2, 0x2222)]),
    "scalar.deref.cell": (1, 0, [(8, 0x77)]),
    "scalar.deref.pc": (1, 0, [(8, 0x04)]),
    "scalar.deref.fp": (5, 4, [(8, 0x10)]),
    "scalar.jump.not_taken": (1, 0, []),
    "scalar.jump.taken_nontrivial_inverse": (3, 0, []),
}


def hx(value: int) -> str:
    return f"{value:032x}"


def inverse(value: int) -> int:
    result, base, exponent = 1, value, (1 << 128) - 2
    while exponent:
        if exponent & 1:
            result = lsc1.field_mul(result, base)
        base = lsc1.field_mul(base, base)
        exponent >>= 1
    return result


def state(endpoint: lsc1.Lsc1Endpoint) -> dict:
    return {
        "txn_state": endpoint.state.value,
        "profile": endpoint.profile.name,
        "committed_pc": endpoint.committed_pc,
        "committed_fp": endpoint.committed_fp,
        "state_valid": endpoint.state_valid,
        "retire_seq": endpoint.retire_seq,
        "last_status": endpoint.last_status.name,
        "last_fault": endpoint.last_fault.name,
        "abort_count": endpoint.abort_count,
    }


def fingerprint(case: dict) -> dict:
    encoded = json.dumps(case, sort_keys=True, separators=(",", ":")).encode()
    return {**case, "fingerprint": "sha256:" + hashlib.sha256(encoded).hexdigest()}


def upstream(case_id: str) -> dict:
    if case_id not in UPSTREAM_EXPECTED:
        return {
            "mode": "protocol_only",
            "reason": "wire/lifecycle behavior has no Program::execute representation",
        }
    cycles, mem_used, memory = UPSTREAM_EXPECTED[case_id]
    next_pc, next_fp, writes = UPSTREAM_TRANSITIONS[case_id]
    return {
        "mode": "program_execute",
        "adapter": "conformance/rust/frozen_adapter.rs",
        "expected": {
            "cycles": cycles,
            "mem_used": mem_used,
            "memory": [hx(value) for value in memory],
        },
        "transition": {
            "next_pc": next_pc,
            "next_fp": next_fp,
            "writes": [
                {"address": address, "value": hx(value)}
                for address, value in writes
            ],
        },
    }


def drive_retire(endpoint: lsc1.Lsc1Endpoint, frame: bytes) -> tuple[bytes, int, bool]:
    """Drive RETIRE while preserving the acceptance-edge DONE observation."""
    sent = 0
    response = bytearray()
    cycles = 0
    done_observed = False
    while cycles < 100_000:
        record = endpoint.step(
            rx_data=frame[sent] if sent < len(frame) else 0,
            rx_valid=sent < len(frame),
            tx_ready=True,
        )
        cycles += 1
        if record.rx_committed:
            sent += 1
        # DONE is asserted by accepting the final RETIRE byte and is sampled
        # here before the following edge clears the one-cycle pulse.
        done_observed |= endpoint.pins().done_pulse
        if record.tx_committed:
            response.append(record.pins.tx_data)
        if sent == len(frame) and response and not endpoint.pins().tx_valid:
            return bytes(response), cycles, done_observed
    raise TimeoutError("RETIRE drive exceeded max_cycles")


def semantic(case_id: str, description: str, coverage: list[str], frame: lsc1.RequestFrame) -> dict:
    endpoint = lsc1.Lsc1Endpoint()
    initial = state(endpoint)
    request = frame.encode()
    result_raw, result_cycles = lsc1.drive(endpoint, request)
    result = lsc1.decode_response(result_raw)
    staged = endpoint.staged
    assert result.status is lsc1.Status.OK and staged is not None
    staged_record = {
        "txn_id": staged.txn_id,
        "opcode": staged.opcode.name,
        "profile": staged.profile.name,
        "pc": staged.pc,
        "fp": staged.fp,
        "next_pc": staged.next_pc,
        "next_fp": staged.next_fp,
        "writes": [{"address": item.address, "value": hx(item.value)} for item in staged.writes],
        "deferred": [{"target": item.target, "local": item.local} for item in staged.deferred],
        "accesses": staged.accesses,
        "execute_cycles": staged.execute_cycles,
        "result_payload_hex": staged.result_payload().hex(),
        "result_crc32": f"{staged.result_crc:08x}",
    }
    retire_request = lsc1.build_retire(
        txn_id=staged.txn_id, result_crc=staged.result_crc
    ).encode()
    retire_raw, retire_cycles, done_observed = drive_retire(endpoint, retire_request)
    retire_response = lsc1.decode_response(retire_raw)
    assert retire_response.status is lsc1.Status.RETIRED
    assert done_observed
    return fingerprint({
        "case_id": case_id,
        "description": description,
        "coverage": coverage,
        "raw": {
            "request_hex": request.hex(),
            "response_hex": result_raw.hex(),
            "request_cycles": result_cycles,
        },
        "initial_state": initial,
        "staged_transition": staged_record,
        "final_state": state(endpoint),
        "retire": {
            "attempted": True,
            "request_hex": retire_request.hex(),
            "response_hex": retire_raw.hex(),
            "response_status": retire_response.status.name,
            "response_payload_hex": retire_response.payload.hex(),
            "cycles": retire_cycles,
            "txn_id": staged.txn_id,
            "result_crc32": f"{staged.result_crc:08x}",
            "retire_seq": endpoint.retire_seq,
            "committed_pc": endpoint.committed_pc,
            "committed_fp": endpoint.committed_fp,
            "done_pulse": done_observed,
        },
        "upstream": upstream(case_id),
    })


def fault(case_id: str, description: str, coverage: list[str], raw: bytes) -> dict:
    endpoint = lsc1.Lsc1Endpoint()
    initial = state(endpoint)
    response, cycles = lsc1.drive(endpoint, raw)
    decoded = lsc1.decode_response(response)
    assert int(decoded.status) >= 0x80
    return fingerprint({
        "case_id": case_id,
        "description": description,
        "coverage": coverage,
        "raw": {"request_hex": raw.hex(), "response_hex": response.hex(), "request_cycles": cycles},
        "initial_state": initial,
        "final_state": state(endpoint),
        "retire": {
            "attempted": False, "request_hex": "", "response_hex": "",
            "response_status": None, "response_payload_hex": "", "cycles": 0,
            "txn_id": None, "result_crc32": None, "retire_seq": 0,
            "committed_pc": 0, "committed_fp": 0, "done_pulse": False,
        },
        "fault": {"status": decoded.status.name, "payload_hex": decoded.payload.hex()},
        "upstream": upstream(case_id),
    })


def lifecycle_cases(reference: lsc1.RequestFrame) -> list[dict]:
    encoded = reference.encode()
    baseline = lsc1.Lsc1Endpoint()
    initial = state(baseline)
    baseline_raw, baseline_cycles = lsc1.drive(baseline, encoded)
    stalled = lsc1.Lsc1Endpoint()
    stalled_raw, stalled_cycles = lsc1.drive(
        stalled, encoded, rx_gaps=[1, 0, 2], tx_gaps=[2, 1, 0]
    )
    assert stalled_raw == baseline_raw and stalled_cycles > baseline_cycles

    endpoint = lsc1.Lsc1Endpoint()
    for byte in encoded[:11]:
        endpoint.step(rx_data=byte, rx_valid=True)
    before_abort = state(endpoint)
    endpoint.step(rx_data=encoded[11], rx_valid=True, tx_ready=True, abort=True)
    abort_case = fingerprint({
        "case_id": "lane.abort.priority",
        "description": "ABORT cancels a same-edge transfer and discards partial receive state.",
        "coverage": ["abort", "priority", "partial_frame"],
        "raw": {"request_hex": encoded[:12].hex(), "response_hex": ""},
        "initial_state": initial,
        "pre_action_state": before_abort,
        "final_state": state(endpoint),
        "retire": {
            "attempted": False, "request_hex": "", "response_hex": "",
            "response_status": None, "response_payload_hex": "", "cycles": 0,
            "txn_id": None, "result_crc32": None, "retire_seq": 0,
            "committed_pc": 0, "committed_fp": 0, "done_pulse": False,
        },
        "lane": {"action": "abort", "same_edge_rx_valid": True, "rx_committed": False},
        "upstream": upstream("lane.abort.priority"),
    })

    reset_initial = state(endpoint)
    endpoint.step(reset_n=False, abort=True, rx_valid=True, rx_data=lsc1.SOF_REQUEST)
    reset_case = fingerprint({
        "case_id": "lane.reset.priority",
        "description": "Active-low reset has priority over ABORT and a candidate transfer.",
        "coverage": ["reset", "abort", "priority"],
        "raw": {"request_hex": f"{lsc1.SOF_REQUEST:02x}", "response_hex": ""},
        "initial_state": reset_initial,
        "final_state": state(endpoint),
        "retire": {
            "attempted": False, "request_hex": "", "response_hex": "",
            "response_status": None, "response_payload_hex": "", "cycles": 0,
            "txn_id": None, "result_crc32": None, "retire_seq": 0,
            "committed_pc": 0, "committed_fp": 0, "done_pulse": False,
        },
        "lane": {"action": "reset", "same_edge_abort": True, "same_edge_rx_valid": True, "rx_committed": False},
        "upstream": upstream("lane.reset.priority"),
    })
    stall_case = fingerprint({
        "case_id": "lane.stall_backpressure.invariant",
        "description": "Input stalls and output backpressure preserve response bytes exactly.",
        "coverage": ["stall", "backpressure", "ready_valid"],
        "raw": {"request_hex": encoded.hex(), "response_hex": stalled_raw.hex()},
        "initial_state": initial,
        "final_state": state(stalled),
        "retire": {
            "attempted": False, "request_hex": "", "response_hex": "",
            "response_status": None, "response_payload_hex": "", "cycles": 0,
            "txn_id": 90, "result_crc32": None, "retire_seq": 0,
            "committed_pc": 0, "committed_fp": 0, "done_pulse": False,
        },
        "lane": {
            "rx_gaps": [1, 0, 2], "tx_gaps": [2, 1, 0],
            "baseline_cycles": baseline_cycles, "stalled_cycles": stalled_cycles,
            "response_matches_baseline": True,
        },
        "upstream": upstream("lane.stall_backpressure.invariant"),
    })
    return [abort_case, reset_case, stall_case]


def build_cases() -> list[dict]:
    g8 = lsc1.field_encode(8)
    cases = [
        semantic("scalar.set.forward", "SET writes one absent destination.", ["SET"], lsc1.build_set_constant(
            txn_id=1, pc=0, fp=0, profile=P, offset=2, constant=0x1234, cell=A)),
        semantic("scalar.xor.forward", "XOR computes an absent result.", ["XOR", "forward"], lsc1.build_binary_op(
            lsc1.Opcode.XOR, txn_id=2, pc=0, fp=0, profile=P, offsets=(0, 1, 2),
            cells=(C(True, 0xDEAD), C(True, 0xBEEF), A))),
        semantic("scalar.mul.forward", "MUL_NATIVE computes an absent result.", ["MUL", "forward"], lsc1.build_binary_op(
            lsc1.Opcode.MUL_NATIVE, txn_id=3, pc=0, fp=0, profile=P, offsets=(0, 1, 2),
            cells=(C(True, 0x53), C(True, 0xCA), A), proposed_inverse=A)),
        semantic("scalar.xor.backsolve_a", "XOR back-solves absent operand A.", ["XOR", "backsolve_a"], lsc1.build_binary_op(
            lsc1.Opcode.XOR, txn_id=4, pc=0, fp=0, profile=P, offsets=(2, 0, 1),
            cells=(A, C(True, 0x1111), C(True, 0x3333)))),
        semantic("scalar.xor.backsolve_b", "XOR back-solves absent operand B.", ["XOR", "backsolve_b"], lsc1.build_binary_op(
            lsc1.Opcode.XOR, txn_id=5, pc=0, fp=0, profile=P, offsets=(0, 2, 1),
            cells=(C(True, 0x1111), A, C(True, 0x3333)))),
        semantic("scalar.deref.cell", "DEREF Cell copies a present local into an absent target.", ["DEREF", "Cell"], lsc1.build_deref(
            lsc1.Opcode.DEREF_CELL, txn_id=6, pc=0, fp=0, profile=P, alpha=0, beta=0,
            gamma=1, pointer=C(True, g8), base=8, target=A, local=C(True, 0x77))),
        semantic("scalar.deref.pc", "DEREF Pc writes g^(pc+2).", ["DEREF", "Pc"], lsc1.build_deref(
            lsc1.Opcode.DEREF_PC, txn_id=7, pc=0, fp=0, profile=P, alpha=0, beta=0,
            gamma=1, pointer=C(True, g8), base=8, target=A, local=C(True, 0))),
        semantic("scalar.deref.fp", "DEREF Fp writes g^fp for a nonzero frame.", ["DEREF", "Fp"], lsc1.build_deref(
            lsc1.Opcode.DEREF_FP, txn_id=8, pc=4, fp=4, profile=P, alpha=0, beta=0,
            gamma=1, pointer=C(True, g8), base=8, target=A, local=C(True, 1))),
        semantic("scalar.jump.not_taken", "Zero condition advances pc and pins the inverse proposal to zero.", ["JUMP", "not_taken"], lsc1.build_jump(
            txn_id=9, pc=0, fp=0, profile=P, offsets=(1, 0, 0),
            cells=(C(True, 0), C(True, 1), C(True, 1)), taken=False, dest_pc=0,
            dest_fp=0, proposed_inverse=A)),
        semantic("scalar.jump.taken_nontrivial_inverse", "Taken JUMP verifies a nontrivial condition inverse and g-power destinations.", ["JUMP", "taken", "inverse"], lsc1.build_jump(
            txn_id=10, pc=1, fp=0, profile=P, offsets=(0, 1, 2),
            cells=(C(True, 0x53), C(True, lsc1.field_encode(3)), C(True, 1)),
            taken=True, dest_pc=3, dest_fp=0, proposed_inverse=C(True, inverse(0x53)))),
    ]
    # Both-absent Cell DEREF is representable only at the protocol boundary:
    # upstream resolves it at end-of-execution, while LSC-1 retires a deferred event.
    cases.append(semantic("protocol.deref.cell.deferred", "DEREF Cell emits a deferred equality when both sides are absent.", ["DEREF", "Cell", "deferred"], lsc1.build_deref(
        lsc1.Opcode.DEREF_CELL, txn_id=11, pc=0, fp=0, profile=P, alpha=0, beta=0,
        gamma=1, pointer=C(True, g8), base=8, target=A, local=A)))

    good = lsc1.build_set_constant(
        txn_id=40, pc=0, fp=0, profile=P, offset=2, constant=1, cell=A
    ).encode()
    bad_crc_version = bytearray(good)
    bad_crc_version[1] = 9
    bad_crc_version[-1] ^= 0x80
    cases.append(fault("malformed.precedence.crc_before_version", "CRC failure precedes version validation.", ["malformed", "precedence", "BAD_CRC"], bytes(bad_crc_version)))
    bad_flags_opcode = bytearray(good)
    bad_flags_opcode[2] = 0xFF
    bad_flags_opcode[3] = 1
    bad_flags_opcode[-4:] = lsc1.u32le(lsc1.crc32(bytes(bad_flags_opcode[:-4])))
    cases.append(fault("malformed.precedence.flags_before_opcode", "Envelope flags failure precedes opcode decoding.", ["malformed", "precedence", "BAD_FLAGS"], bytes(bad_flags_opcode)))
    bad_length = bytearray(good)
    bad_length[4:6] = lsc1.u16le(len(good) - lsc1.REQUEST_HEADER_BYTES - lsc1.CRC_BYTES - 1)
    shortened = bytes(bad_length[:-1])
    shortened = shortened[:-4] + lsc1.u32le(lsc1.crc32(shortened[:-4]))
    cases.append(fault(
        "malformed.length.decoded_txn",
        "A fixed-length mismatch preserves the complete decoded txn_id prefix.",
        ["malformed", "BAD_LENGTH", "txn_id", "decoded"], shortened,
    ))
    truncated_payload = (
        good[:lsc1.REQUEST_HEADER_BYTES]
        + good[lsc1.REQUEST_HEADER_BYTES:lsc1.REQUEST_HEADER_BYTES + 3]
    )
    truncated_payload = (
        truncated_payload[:4] + lsc1.u16le(3) + truncated_payload[6:]
    )
    truncated_payload += lsc1.u32le(lsc1.crc32(truncated_payload))
    cases.append(fault(
        "malformed.length.partial_txn",
        "A fixed-length mismatch zero-extends an available partial txn_id prefix.",
        ["malformed", "BAD_LENGTH", "txn_id", "partial"], truncated_payload,
    ))
    bad_pointer = lsc1.build_deref(
        lsc1.Opcode.DEREF_PC, txn_id=43, pc=0, fp=0, profile=P, alpha=0, beta=0,
        gamma=1, pointer=C(True, 7), base=8, target=C(True, 1), local=A,
    ).encode()
    cases.append(fault("error.precedence.pointer_before_write_conflict", "Pointer validation precedes a conflicting target write.", ["error", "precedence", "BAD_POINTER"], bad_pointer))
    cases.extend(lifecycle_cases(lsc1.build_set_constant(
        txn_id=90, pc=0, fp=0, profile=P, offset=2, constant=0x55, cell=A
    )))
    return cases


def main() -> None:
    corpus = {
        "schema": "lean-silicon-conformance-v2",
        "frozen_upstream": {
            "repository": "https://github.com/leanEthereum/leanVM-b.git",
            "commit": UPSTREAM_COMMIT,
        },
        "cases": build_cases(),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(corpus, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(ROOT)} cases={len(corpus['cases'])}")


if __name__ == "__main__":
    main()

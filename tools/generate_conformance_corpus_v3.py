#!/usr/bin/env python3
"""Deterministically freeze the BLAKE3 service lifecycle conformance corpus v3."""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from host.blake3_service import (  # noqa: E402
    ModelServiceAdapter,
    ServiceKey,
    ServiceResponse,
    ServiceSemanticError,
    ServiceStatus,
)
from host.protocol import protocol as lsc1  # noqa: E402

OUTPUT = ROOT / "conformance/corpus-v3.json"
SESSION_EPOCH = 0x1122334455667788
TXN_ID = 0x10203040


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def fingerprint(case: dict) -> dict:
    return {**case, "fingerprint": "sha256:" + hashlib.sha256(canonical(case)).hexdigest()}


def exchange(endpoint: lsc1.Lsc1Endpoint, frame: lsc1.RequestFrame) -> tuple[bytes, lsc1.ResponseFrame]:
    raw, _ = lsc1.drive(endpoint, frame.encode())
    return raw, lsc1.decode_response(raw)


def request_frame(*, txn_id: int = TXN_ID, metadata: int = 64 << 64,
                  out: tuple[lsc1.Cell, lsc1.Cell] = (lsc1.ABSENT, lsc1.ABSENT)) -> lsc1.RequestFrame:
    return lsc1.build_blake3(
        txn_id=txn_id, pc=2, fp=64, profile=lsc1.Profile.INTERPRETER_COMPAT,
        message_offsets=(0, 1, 2, 3), cv_offset=8, out_offset=10,
        metadata=metadata,
        message_cells=tuple(lsc1.Cell(True, value) for value in (11, 22, 33, 44)),
        cv_cells=tuple(lsc1.Cell(True, value) for value in (55, 66)),
        out_cells=out,
    )


def nominal_case() -> dict:
    endpoint = lsc1.Lsc1Endpoint()
    request = request_frame()
    required_raw, required_reply = exchange(endpoint, request)
    assert required_reply.status is lsc1.Status.SERVICE_REQUIRED
    assert len(required_reply.payload) == 122
    adapter = ModelServiceAdapter(SESSION_EPOCH)
    required = adapter.accept_required(required_reply.payload)
    response = adapter.compute(required)
    response_frame = adapter.to_v1(response)
    result_raw, result_reply = exchange(endpoint, response_frame)
    assert result_reply.status is lsc1.Status.OK and endpoint.staged is not None
    retire_frame = lsc1.build_retire(txn_id=TXN_ID, result_crc=lsc1.crc32(result_reply.payload))
    retire_raw, retire_reply = exchange(endpoint, retire_frame)
    assert retire_reply.status is lsc1.Status.RETIRED
    adapter.complete(required.key)
    return fingerprint({
        "case_id": "blake3.lifecycle.nominal",
        "description": "Byte-exact BLAKE3_REQUEST through SERVICE_REQUIRED, SERVICE_RESPONSE, RESULT, and RETIRE.",
        "coverage": ["BLAKE3_REQUEST", "SERVICE_REQUIRED", "SERVICE_RESPONSE", "RESULT", "RETIRE"],
        "detected": True,
        "statuses": [required_reply.status.name, result_reply.status.name, retire_reply.status.name],
        "service_required": {
            "internal_payload_hex": required_reply.payload.hex(),
            "host_envelope_hex": required.encode().hex(),
        },
        "service_response": {
            "digest_hex": response.digest.hex(),
            "host_envelope_hex": response.encode().hex(),
        },
        "wire": {
            "blake3_request_hex": request.encode().hex(),
            "service_required_frame_hex": required_raw.hex(),
            "service_response_frame_hex": response_frame.encode().hex(),
            "result_frame_hex": result_raw.hex(),
            "retire_request_hex": retire_frame.encode().hex(),
            "retire_response_hex": retire_raw.hex(),
        },
        "final": {"retire_seq": endpoint.retire_seq, "committed_pc": endpoint.committed_pc,
                  "committed_fp": endpoint.committed_fp, "state": endpoint.state.value},
    })


def rejection(case_id: str, description: str, coverage: list[str], evidence: dict) -> dict:
    return fingerprint({"case_id": case_id, "description": description,
                        "coverage": coverage, "detected": True, "evidence": evidence})


def binding_cases() -> list[dict]:
    endpoint = lsc1.Lsc1Endpoint()
    _, reply = exchange(endpoint, request_frame())
    adapter = ModelServiceAdapter(SESSION_EPOCH)
    required = adapter.accept_required(reply.payload)
    good = adapter.compute(required)
    cases = []
    mutations = (
        ("txn_id", ServiceKey(SESSION_EPOCH, TXN_ID + 1, required.key.service_id, required.key.kind)),
        ("service_id", ServiceKey(SESSION_EPOCH, TXN_ID, required.key.service_id + 1, required.key.kind)),
        ("kind", ServiceKey(SESSION_EPOCH, TXN_ID, required.key.service_id, required.key.kind + 1)),
    )
    for field, key in mutations:
        mutated = ServiceResponse(key, ServiceStatus.OK, good.digest)
        try:
            adapter.to_v1(mutated)
        except ServiceSemanticError as error:
            cases.append(rejection(
                f"blake3.reject.{field}", f"A SERVICE_RESPONSE with the wrong {field} is rejected.",
                ["binding", field, "SERVICE_RESPONSE"],
                {"host_envelope_hex": mutated.encode().hex(), "error": str(error)},
            ))
        else:  # pragma: no cover
            raise AssertionError(f"{field} mutation was accepted")

    for field, offset, mask in (
        ("counter", 106, 1),
        ("block_len", 114, 0x7F),  # 64 -> 63, remaining within the valid range.
        ("flags", 118, 1),
    ):
        mutated = bytearray(reply.payload)
        mutated[offset] ^= mask
        try:
            adapter.accept_required(bytes(mutated))
        except ServiceSemanticError as error:
            cases.append(rejection(
                f"blake3.reject.metadata.{field}", f"A retry that changes {field} metadata is rejected.",
                ["binding", "metadata", field, "SERVICE_REQUIRED"],
                {"internal_payload_hex": bytes(mutated).hex(), "error": str(error)},
            ))
        else:  # pragma: no cover
            raise AssertionError(f"metadata {field} mutation was accepted")

    adapter.complete(required.key)
    try:
        adapter.accept_required(reply.payload)
    except ServiceSemanticError as error:
        cases.append(rejection(
            "blake3.reject.replay", "A completed SERVICE_REQUIRED key cannot be replayed.",
            ["binding", "replay", "SERVICE_REQUIRED"],
            {"internal_payload_hex": reply.payload.hex(), "error": str(error)},
        ))
    else:  # pragma: no cover
        raise AssertionError("replay was accepted")
    return cases


def digest_case() -> dict:
    probe = lsc1.Lsc1Endpoint()
    _, reply = exchange(probe, request_frame())
    adapter = ModelServiceAdapter(SESSION_EPOCH)
    required = adapter.accept_required(reply.payload)
    good = adapter.compute(required)
    out = (lsc1.Cell(True, int.from_bytes(good.digest[:16], "little")),
           lsc1.Cell(True, int.from_bytes(good.digest[16:], "little")))
    endpoint = lsc1.Lsc1Endpoint()
    _, bound_reply = exchange(endpoint, request_frame(out=out))
    bound_adapter = ModelServiceAdapter(SESSION_EPOCH)
    bound = bound_adapter.accept_required(bound_reply.payload)
    bad_digest = bytes((good.digest[0] ^ 1,)) + good.digest[1:]
    mutated = ServiceResponse(bound.key, ServiceStatus.OK, bad_digest)
    raw, decoded = exchange(endpoint, bound_adapter.to_v1(mutated))
    assert decoded.status is lsc1.Status.WRITE_CONFLICT and endpoint.state is lsc1.TxnState.IDLE
    return rejection(
        "blake3.reject.digest", "A digest conflicting with present output cells is rejected and discarded.",
        ["binding", "digest", "WRITE_CONFLICT", "SERVICE_RESPONSE"],
        {"host_envelope_hex": mutated.encode().hex(), "response_frame_hex": raw.hex(),
         "status": decoded.status.name, "final_state": endpoint.state.value},
    )


def control_cases() -> list[dict]:
    cases = []
    for action in ("abort", "reset"):
        endpoint = lsc1.Lsc1Endpoint()
        _, reply = exchange(endpoint, request_frame())
        adapter = ModelServiceAdapter(SESSION_EPOCH)
        required = adapter.accept_required(reply.payload)
        stale = adapter.compute(required)
        if action == "abort":
            endpoint.step(abort=True)
            adapter.abort()
        else:
            endpoint.step(reset_n=False)
            adapter.reset(SESSION_EPOCH + 1)
        try:
            adapter.to_v1(stale)
        except ServiceSemanticError as error:
            cases.append(rejection(
                f"blake3.control.{action}", f"{action.upper()} invalidates the outstanding host response.",
                [action, "binding", "stale_response"],
                {"stale_host_envelope_hex": stale.encode().hex(), "error": str(error),
                 "endpoint_state": endpoint.state.value},
            ))
        else:  # pragma: no cover
            raise AssertionError(f"stale response survived {action}")
    return cases


def build_cases() -> list[dict]:
    return [nominal_case(), *binding_cases(), digest_case(), *control_cases()]


def render_corpus() -> bytes:
    corpus = {
        "schema": "lean-silicon-conformance-v3",
        "scope": "BLAKE3 service lifecycle over the merged LSC-1 v1 software boundary",
        "base_commit": "3beb2cb7da772f3c819c8055249c787ea92185d1",
        "cases": build_cases(),
    }
    return (json.dumps(corpus, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def main() -> None:
    OUTPUT.write_bytes(render_corpus())
    print(f"wrote {OUTPUT.relative_to(ROOT)} cases={len(build_cases())}")


if __name__ == "__main__":
    main()

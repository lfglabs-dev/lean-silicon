#!/usr/bin/env python3
"""Validate the immutable BLAKE3 service lifecycle conformance corpus v3."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORPUS = ROOT / "conformance/corpus-v3.json"
SCHEMA = ROOT / "conformance/schema-v3.json"
sys.path.insert(0, str(ROOT))

from tools.generate_conformance_corpus_v3 import canonical, render_corpus  # noqa: E402


class SemanticFailure(RuntimeError):
    pass


def validate() -> dict:
    try:
        import jsonschema
        corpus = json.loads(CORPUS.read_text())
        schema = json.loads(SCHEMA.read_text())
    except (ImportError, OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot load v3 corpus/schema: {error}") from error
    jsonschema.Draft202012Validator.check_schema(schema)
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(corpus),
                    key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        location = ".".join(str(item) for item in error.absolute_path) or "<root>"
        raise SemanticFailure(f"schema violation at {location}: {error.message}")
    if CORPUS.read_bytes() != render_corpus():
        raise SemanticFailure("corpus-v3.json is not the byte-exact deterministic generator output")
    seen = set()
    for case in corpus["cases"]:
        case_id = case["case_id"]
        if case_id in seen:
            raise SemanticFailure(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        body = {key: value for key, value in case.items() if key != "fingerprint"}
        expected = "sha256:" + hashlib.sha256(canonical(body)).hexdigest()
        if case["fingerprint"] != expected:
            raise SemanticFailure(f"{case_id}: fingerprint mismatch")
    nominal = next(case for case in corpus["cases"] if case["case_id"] == "blake3.lifecycle.nominal")
    lengths = (
        len(bytes.fromhex(nominal["service_required"]["internal_payload_hex"])),
        len(bytes.fromhex(nominal["service_required"]["host_envelope_hex"])),
        len(bytes.fromhex(nominal["service_response"]["host_envelope_hex"])),
    )
    if lengths != (122, 131, 53):
        raise SemanticFailure(f"byte boundary mismatch: {lengths}")
    required = {
        "blake3.lifecycle.nominal", "blake3.reject.txn_id", "blake3.reject.service_id",
        "blake3.reject.kind", "blake3.reject.digest", "blake3.reject.metadata.counter",
        "blake3.reject.metadata.block_len", "blake3.reject.metadata.flags",
        "blake3.reject.replay", "blake3.control.abort", "blake3.control.reset",
    }
    if seen != required:
        raise SemanticFailure(f"case inventory mismatch: missing={sorted(required-seen)} extra={sorted(seen-required)}")
    return corpus


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true",
                        help="validate schema, fingerprints, inventory, lengths, and regeneration")
    args = parser.parse_args()
    if not args.validate_only:
        parser.error("--validate-only is required")
    try:
        corpus = validate()
    except SemanticFailure as error:
        print(f"SEMANTIC FAILURE: {error}", file=sys.stderr)
        return 1
    except RuntimeError as error:
        print(f"INFRASTRUCTURE FAILURE: {error}", file=sys.stderr)
        return 2
    print(f"PASS corpus cases={len(corpus['cases'])} fingerprints=verified schema=v3 byte_boundaries=122/131/53")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

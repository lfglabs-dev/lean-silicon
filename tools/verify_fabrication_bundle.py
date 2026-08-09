#!/usr/bin/env python3
"""Fail-closed, CPU-only verification of the v0.1.1 fabrication bundle."""

import csv
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release" / "v0.1.1"
RECEIPT_TESTS = {
    "precheck": {
        "Magic DRC", "KLayout FEOL", "KLayout BEOL", "KLayout offgrid",
        "KLayout pin label overlapping drawing", "KLayout zero area", "KLayout Checks",
        "Pin check", "Boundary check", "Power pin check", "Layer check", "Cell name check",
        "urpm/nwell check", "Analog pin check", "Verilog syntax check",
    },
    "gate_level": {
        "lsc1u_all_retained_operations", "lsc1u_reset_ena_framing_and_backpressure",
        "lsc1u_reset_ena_every_state_and_consecutive_commands",
        "lsc1u_little_endian_polynomial_vectors",
        "lsc1u_shared_mutation_corpus_and_latency",
    },
}


def fail(message: str) -> None:
    raise SystemExit(f"fabrication bundle invalid: {message}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        fail(f"{label} mismatch: {actual!r} != {expected!r}")


def validate_receipt(data: bytes, spec: dict, name: str) -> None:
    root = ET.fromstring(data)
    tests = root.findall(".//testcase")
    failures = root.findall(".//failure") + root.findall(".//error")
    skipped = root.findall(".//skipped")
    test_names = [test.get("name") for test in tests]
    required = RECEIPT_TESTS[name]
    if set(spec["required_tests"]) != required:
        fail(f"{name} manifest case set is not canonical")
    if not required or len(test_names) != len(set(test_names)) or set(test_names) != required or failures or skipped:
        fail(f"{name} is vacuous, incomplete, duplicated, unexpected, skipped, or records failures")


def main() -> None:
    manifest_path = Path(sys.argv[1]) if len(sys.argv) == 2 else RELEASE / "FABRICATION_MANIFEST.json"
    if len(sys.argv) > 2:
        fail("usage: verify_fabrication_bundle.py [manifest.json]")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"manifest unreadable: {exc}")
    if manifest.get("schema_version") != 1 or manifest.get("status") != "pre-silicon-no-go":
        fail("unsupported schema or unsafe status")

    checksum_lines = (RELEASE / "SHA256SUMS.txt").read_text().splitlines()
    package_sums = {}
    for line in checksum_lines:
        try:
            expected, name = line.split("  ", 1)
        except ValueError:
            fail("malformed package SHA256SUMS line")
        if name in package_sums or len(expected) != 64:
            fail("duplicate path or malformed digest in package SHA256SUMS")
        package_sums[name] = expected
    required_package = {
        "MANIFEST.json", "FABRICATION_MANIFEST.json", "FABRICATION_READINESS.md", "RELEASE.md",
        "evidence/gatelevel-results.xml", "evidence/precheck-results.xml",
        "evidence/tt_submission-9004116698.zip",
    }
    if set(package_sums) != required_package:
        fail("package SHA256SUMS coverage is incomplete or unexpected")
    for name, expected in package_sums.items():
        if digest((RELEASE / name).read_bytes()) != expected:
            fail(f"package checksum mismatch: {name}")

    release_manifest = json.loads((RELEASE / "MANIFEST.json").read_text())
    canonical_manifest = json.loads((RELEASE / "FABRICATION_MANIFEST.json").read_text())
    require_equal(manifest, canonical_manifest, "fabrication manifest identity")
    authoritative_payload_sums = {
        item["path"]: item["sha256"] for item in release_manifest["payload_checksums"]
    }

    source = manifest["source"]
    commit = source["commit"]
    tree = source["tree"]
    actual_tree = subprocess.run(
        ["git", "show", "-s", "--format=%T", commit], cwd=ROOT,
        check=True, text=True, capture_output=True,
    ).stdout.strip()
    if actual_tree != tree:
        fail(f"commit/tree mismatch: {actual_tree} != {tree}")

    archive_spec = manifest["retained_archive"]
    require_equal(archive_spec, canonical_manifest["retained_archive"], "retained archive identity")
    canonical_archive = next(
        item for item in release_manifest["physical_artifacts"]
        if item.get("retained_path") == "release/v0.1.1/evidence/tt_submission-9004116698.zip"
    )
    require_equal(archive_spec["github_artifact_id"], canonical_archive["id"], "retained archive artifact ID")
    require_equal(archive_spec["sha256"], canonical_archive["archive_sha256"], "retained archive authoritative checksum")
    require_equal(archive_spec["workflow_run"], release_manifest["ci"]["physical_run"]["id"], "retained archive workflow run")
    archive = RELEASE / archive_spec["path"]
    archive_bytes = archive.read_bytes()
    if digest(archive_bytes) != archive_spec["sha256"]:
        fail("retained archive checksum mismatch")

    required = {"gds", "oas", "netlist", "lef", "pinout", "config", "config_merged", "user_config", "user_config_tcl", "pdk", "metrics"}
    entries = manifest["payload"]
    require_equal(entries, canonical_manifest["payload"], "payload class-to-member mapping")
    classes = [entry["class"] for entry in entries]
    if set(classes) != required or len(classes) != len(required):
        fail("payload classes are missing, duplicated, or unexpected")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as bundle:
        member_list = bundle.namelist()
        members = set(member_list)
        if len(members) != len(member_list):
            fail("retained archive has duplicate member names")
        extracted = {}
        for entry in entries:
            name = entry["member"]
            if name not in members:
                fail(f"missing archive member: {name}")
            data = bundle.read(name)
            if len(data) < entry["min_bytes"]:
                fail(f"vacuous payload: {name}")
            if digest(data) != entry["sha256"]:
                fail(f"payload checksum mismatch: {name}")
            extracted[entry["class"]] = data

        commit_record = json.loads(bundle.read("tt_submission/commit_id.json"))
        require_equal(commit_record.get("repo"), "https://github.com/lfglabs-dev/lean-silicon", "archive source repository")
        require_equal(commit_record.get("commit"), commit, "archive source commit")
        require_equal(commit_record.get("workflow_url"), f"https://github.com/lfglabs-dev/lean-silicon/actions/runs/{archive_spec['workflow_run']}", "archive workflow")

        source_members = {
            "src/tt_um_lfglabs_lsc1u.sv": "src/tt_um_lfglabs_lsc1u.sv",
            "src/lsc1u_core.sv": "src/lsc1u_core.sv",
            "src/gf2n_mul_bitstream.sv": "src/gf2n_mul_bitstream.sv",
            "src/gf128_mul_bitstream.sv": "src/gf128_mul_bitstream.sv",
        }
        for git_path, member in source_members.items():
            committed = subprocess.run(
                ["git", "show", f"{commit}:{git_path}"], cwd=ROOT,
                check=True, capture_output=True,
            ).stdout
            if bundle.read(member) != committed:
                fail(f"archive source does not match pinned commit: {member}")

    for kind in ("config", "config_merged", "user_config", "pdk"):
        try:
            value = json.loads(extracted[kind])
        except json.JSONDecodeError as exc:
            fail(f"invalid {kind} JSON: {exc}")
        if not isinstance(value, dict) or not value:
            fail(f"vacuous {kind} JSON")
        extracted[kind] = value
    require_equal(extracted["pdk"].get("FLOW_NAME"), "LibreLane", "physical flow name")
    require_equal(extracted["pdk"].get("FLOW_VERSION"), manifest["toolchain"]["physical_flow"].removeprefix("LibreLane "), "physical flow version")
    pdk_identity = f"{extracted['pdk'].get('PDK')}/{extracted['pdk'].get('PDK_SOURCE')}@{extracted['pdk'].get('PDK_VERSION')}"
    require_equal(pdk_identity, manifest["toolchain"]["pdk"], "PDK identity")
    require_equal(extracted["config_merged"].get("DESIGN_NAME"), "tt_um_lfglabs_lsc1u", "top design")
    require_equal(extracted["config_merged"].get("CLOCK_PERIOD"), 40, "clock period")
    pinout = extracted["pinout"].decode()
    for token in ("ui[0]", "ui[7]", "uo[0]", "uo[7]", "uio[0]", "uio[7]", "clock_hz:     25000000"):
        if token not in pinout:
            fail(f"pinout lacks {token}")

    metrics = dict(csv.reader(io.StringIO(extracted["metrics"].decode())))
    receipts = manifest["receipts"]
    require_equal(receipts, canonical_manifest["receipts"], "receipt projections and metric assertions")
    require_equal(
        receipts["metrics_zero_keys"], canonical_manifest["receipts"]["metrics_zero_keys"],
        "required zero-metric set",
    )
    for key in receipts["metrics_zero_keys"]:
        if key not in metrics or float(metrics[key]) != 0:
            fail(f"required zero metric failed: {key}={metrics.get(key)!r}")
    density_key = receipts["density_key"]
    if float(metrics.get(density_key, "nan")) != receipts["density_expected"]:
        fail("density metric missing or changed")

    for name in ("precheck", "gate_level"):
        spec = receipts[name]
        receipt = RELEASE / spec["path"]
        data = receipt.read_bytes()
        if digest(data) != spec["sha256"]:
            fail(f"{name} receipt checksum mismatch")
        authoritative_path = {
            "precheck": "artifacts/precheck/results.xml",
            "gate_level": "artifacts/gatelevel-results.xml",
        }[name]
        require_equal(
            spec["source_payload_sha256"], authoritative_payload_sums.get(authoritative_path),
            f"{name} source receipt identity",
        )
        validate_receipt(data, spec, name)

    external = manifest["external_exact_run_payload"]
    require_equal(external, canonical_manifest["external_exact_run_payload"], "external exact-run payload identity")
    canonical_external = next(
        item for item in release_manifest["physical_artifacts"] if item["id"] == external["artifact_id"]
    )
    require_equal(external["archive_sha256"], canonical_external["archive_sha256"], "external archive authoritative checksum")
    if (
        external["def"].get("path") != "runs/wokwi/final/def/tt_um_lfglabs_lsc1u.def"
        or re.fullmatch(r"[0-9a-f]{64}", external["def"].get("sha256", "")) is None
        or not external.get("limitation")
    ):
        fail("external DEF identity/limitation is incomplete")
    receipt_count = sum(len(receipts[name]["required_tests"]) for name in ("precheck", "gate_level"))
    print(f"verified {manifest['candidate']}: {len(entries)} payload classes, {receipt_count} named receipt cases, zero required flow counters")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile, ValueError, ET.ParseError) as exc:
        fail(str(exc))

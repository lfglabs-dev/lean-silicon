#!/usr/bin/env python3
"""Fail-closed, CPU-only verification of the v0.1.1 fabrication bundle."""

import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release" / "v0.1.1"


def fail(message: str) -> None:
    raise SystemExit(f"fabrication bundle invalid: {message}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    archive = RELEASE / archive_spec["path"]
    archive_bytes = archive.read_bytes()
    if digest(archive_bytes) != archive_spec["sha256"]:
        fail("retained archive checksum mismatch")

    required = {"gds", "oas", "netlist", "lef", "pinout", "config", "config_merged", "user_config", "user_config_tcl", "pdk", "metrics"}
    entries = manifest["payload"]
    classes = [entry["class"] for entry in entries]
    if set(classes) != required or len(classes) != len(required):
        fail("payload classes are missing, duplicated, or unexpected")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as bundle:
        members = set(bundle.namelist())
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

    for kind in ("config", "config_merged", "user_config", "pdk"):
        try:
            value = json.loads(extracted[kind])
        except json.JSONDecodeError as exc:
            fail(f"invalid {kind} JSON: {exc}")
        if not isinstance(value, dict) or not value:
            fail(f"vacuous {kind} JSON")
    pinout = extracted["pinout"].decode()
    for token in ("ui[0]", "ui[7]", "uo[0]", "uo[7]", "uio[0]", "uio[7]", "clock_hz:     25000000"):
        if token not in pinout:
            fail(f"pinout lacks {token}")

    metrics = dict(csv.reader(io.StringIO(extracted["metrics"].decode())))
    receipts = manifest["receipts"]
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
        root = ET.fromstring(data)
        tests = root.findall(".//testcase")
        failures = root.findall(".//failure") + root.findall(".//error")
        if len(tests) < spec["minimum_tests"] or failures:
            fail(f"{name} is vacuous or records failures")

    external = manifest["external_exact_run_payload"]
    if not external.get("artifact_id") or len(external["def"]["sha256"]) != 64 or not external.get("limitation"):
        fail("external DEF identity/limitation is incomplete")
    print(f"verified {manifest['candidate']}: {len(entries)} payload classes, 20 executable receipt tests, zero signoff counters")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile, ValueError, ET.ParseError) as exc:
        fail(str(exc))

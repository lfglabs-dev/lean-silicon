#!/usr/bin/env python3
"""Fail-closed verification of two preserved clean ULX3S host builds."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "evidence/lsc1-09-cleanroom/reproduction-receipt.json"
EVIDENCE = ROOT / "evidence/lsc1-09-cleanroom"
ARCHIVE = ROOT / "results/ulx3s-lsc1-packet-20260726"
SOURCE = "adc3e2c5b86fb08e1b0225573486ae08af4ac194"
SOURCE_TREE = "cec1a2ede2202e7889dfec4165d658f8d3e415d5"
BASE = "5610ea221dd82b5749690043e8c3665b2be9ced8"
BASE_TREE = "50a1741b7377a1649540af6431056b3da53320e8"
ARTIFACTS = {
    "ulx3s_lsc1_packet.bit": "226514183384b875821426b8c4d338508d8cff08cd12cb8e39c9162db37e3b9e",
    "ulx3s_lsc1_packet.config": "0737bbafae6704139ad9de2669a4e43f64d02644ce7cb9fc7bef336b28b7bf6b",
    "ulx3s_lsc1_packet.svf": "0ad6510adeb1afbc3b20bdbc96528211a2d2e38ebcee398fdeb82acb3b1ad0ee",
}
TOOLS = {
    "yosys": "Yosys 0.33 (git sha1 2584903a060)",
    "nextpnr-ecp5": '"nextpnr-ecp5" -- Next Generation Place and Route (Version nextpnr-0.11.1)',
    "ecppack": "Project Trellis ecppack Version 1.4-2build4",
}
OPTIONS = ["--85k", "--package", "CABGA381", "--seed", "2", "--placer", "static", "--no-tmdriv", "--router", "router1"]
RUN_FILES = {
    "SHA256SUMS", "SOURCE_MANIFEST.txt", "build.stderr", "build.stdout",
    "ecppack.log", "nextpnr.log", "timing.txt", "tool_versions.txt",
    *ARTIFACTS, "yosys.log",
}


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def parse_hash_manifest(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        require(len(fields) == 2 and re.fullmatch(r"[0-9a-f]{64}", fields[0]) is not None,
                f"malformed hash manifest {path.name}")
        require(fields[1] not in result, f"duplicate hash manifest entry {fields[1]}")
        result[fields[1]] = fields[0]
    return result


def verify_source_manifest(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    require(lines[:3] == ["=== SOURCE PROVENANCE ===", f"revision: {SOURCE}",
                          "inputs-match-revision: yes"], "source manifest identity")
    entries: dict[str, str] = {}
    for line in lines[3:]:
        fields = line.split()
        require(len(fields) == 2 and re.fullmatch(r"[0-9a-f]{64}", fields[0]) is not None,
                "malformed source manifest")
        require(fields[1] not in entries, f"duplicate source input {fields[1]}")
        entries[fields[1]] = fields[0]
    require(len(entries) == 25, "complete source manifest")
    for name, expected in entries.items():
        try:
            payload = subprocess.check_output(["git", "show", f"{BASE}:{name}"], cwd=ROOT)
        except subprocess.CalledProcessError as error:
            raise ValueError(f"source input absent at durable base anchor: {name}") from error
        require(hashlib.sha256(payload).hexdigest() == expected,
                f"source input differs from durable base anchor: {name}")


def verify_run(run: dict, evidence_root: Path) -> dict[str, str]:
    run_id = run.get("id", "")
    require(run_id in {"clean-build-1", "clean-build-2"}, "independent run identities")
    require(run.get("checkout") == "separate clean clone detached at build_source", "isolated checkout")
    require(run.get("pre_build_tracked_clean") is True, "clean checkout")
    require(run.get("exit_code") == 0, "normal exit")
    directory = evidence_root / run_id
    require(directory.is_dir(), f"missing run evidence {run_id}")
    actual_names = {item.name for item in directory.iterdir() if item.is_file()}
    require(actual_names == RUN_FILES, f"complete run evidence {run_id}")
    expected_hashes = run.get("evidence_sha256")
    require(isinstance(expected_hashes, dict) and set(expected_hashes) == RUN_FILES,
            f"complete evidence hash set {run_id}")
    actual_hashes = {name: sha(directory / name) for name in RUN_FILES}
    require(actual_hashes == expected_hashes, f"preserved evidence hashes {run_id}")

    verify_source_manifest(directory / "SOURCE_MANIFEST.txt")
    require(parse_hash_manifest(directory / "SHA256SUMS") == ARTIFACTS,
            f"artifact manifest {run_id}")
    for name, expected in ARTIFACTS.items():
        require(actual_hashes[name] == expected, f"generated artifact {run_id} {name}")
    versions = (directory / "tool_versions.txt").read_text(encoding="utf-8")
    require(all(value in versions for value in TOOLS.values()), f"tool versions {run_id}")
    require((directory / "build.stderr").read_bytes() == b"", f"build stderr {run_id}")
    stdout = (directory / "build.stdout").read_text(encoding="utf-8")
    require("inputs-match-revision: yes" in stdout and "PASS at 10.00 MHz" in stdout
            and f"sha256: {ARTIFACTS['ulx3s_lsc1_packet.bit']}" in stdout,
            f"build command receipt {run_id}")
    nextpnr = (directory / "nextpnr.log").read_text(encoding="utf-8")
    require("Info: Program finished normally." in nextpnr, f"nextpnr completion {run_id}")
    require("Derived frequency constraint of 10.0 MHz for net core_clk" in nextpnr
            and "Max frequency for clock '$glbnet$core_clk': 15.32 MHz (PASS at 10.00 MHz)" in nextpnr,
            f"10 MHz timing {run_id}")
    timing_lines = [line for line in nextpnr.splitlines()
                    if re.search(r"Input frequency of PLL|Derived frequency constraint|Max frequency|Slack", line)][-8:]
    require((directory / "timing.txt").read_text(encoding="utf-8").splitlines() == timing_lines,
            f"timing receipt consistency {run_id}")
    require("Number of cells:              39206" in (directory / "yosys.log").read_text(encoding="utf-8"),
            f"yosys completion {run_id}")
    return actual_hashes


def verify(path: Path = RECEIPT, evidence_root: Path = EVIDENCE) -> None:
    r = json.loads(path.read_text(encoding="utf-8"))
    require(r.get("schema") == "lean-silicon.lsc1-ulx3s-cleanroom-reproduction.v2", "schema")
    require(r.get("scoper") == "99f65947-0cdb-4d83-a569-d3bf3d1458ae", "scoper")
    require(r.get("base_commit") == BASE, "base commit")
    source = r.get("build_source", {})
    require(source == {"commit": SOURCE, "tree": SOURCE_TREE, "inputs_match_revision": True}, "source identity")
    require(git("rev-parse", f"{BASE}^{{tree}}") == BASE_TREE, "durable base anchor tree")
    scope = r.get("scope", {})
    require(scope.get("design") == "full LSC-1 host-prepared packet UART endpoint", "full LSC-1 scope")
    for key in ("host_fetch", "memory_expansion", "physical_hardware", "end_to_end", "universal_or_unbounded", "later_roadmap_work"):
        require(scope.get(key) is False, f"scope boundary {key}")
    layers = r.get("evidence_layers", {})
    require(set(layers) == {"executable_model", "lean", "authored_rtl", "netlist", "place_and_route", "physical_hardware"}, "evidence layer separation")
    require(r.get("toolchain") == TOOLS, "toolchain")
    require(r.get("command") == ["./fpga/ulx3s/build_packet_uart.sh"], "command")
    require(r.get("nextpnr_options") == OPTIONS, "nextpnr options")
    require(r.get("required_core_clock_mhz") == 10.0, "clock requirement")
    require(parse_hash_manifest(ARCHIVE / "SHA256SUMS") == ARTIFACTS, "archived artifact manifest")
    for name, expected in ARTIFACTS.items():
        require(sha(ARCHIVE / name) == expected, f"archived hash {name}")
    runs = r.get("runs")
    require(isinstance(runs, list) and len(runs) == 2, "exactly two runs")
    require({x.get("id") for x in runs if isinstance(x, dict)} == {"clean-build-1", "clean-build-2"}, "independent run identities")
    hashes = {run["id"]: verify_run(run, evidence_root) for run in runs}
    require(hashes["clean-build-1"]["nextpnr.log"] != hashes["clean-build-2"]["nextpnr.log"]
            and hashes["clean-build-1"]["yosys.log"] != hashes["clean-build-2"]["yosys.log"],
            "independent run receipts")
    require(r.get("conclusion") == "two isolated clean host builds reproduced the archived packet bitstream artifacts byte-for-byte", "conclusion")


def main() -> int:
    try:
        verify()
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, OSError, subprocess.CalledProcessError) as error:
        print(f"FAIL reproduction receipt: {error}", file=sys.stderr)
        return 1
    print("PASS two-run clean-room ULX3S LSC-1 host-build reproduction")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

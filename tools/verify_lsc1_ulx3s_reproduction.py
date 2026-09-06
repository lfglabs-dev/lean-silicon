#!/usr/bin/env python3
"""Fail-closed verification of the two-run host-build reproduction receipt."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "evidence/lsc1-09-cleanroom/reproduction-receipt.json"
ARCHIVE = ROOT / "results/ulx3s-lsc1-packet-20260726"
SOURCE = "fde1b885a56b98391833f4632676f14d1e3e2f9c"
BASE = "5610ea221dd82b5749690043e8c3665b2be9ced8"
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
RAW_RECEIPTS = {
    "clean-build-1": {
        "SHA256SUMS": "cfe3dd6c384c54aedef2221263aa7b401ccf677e874e320b567a0359aaa515cf",
        "tool_versions.txt": "2e986e53019b3d9e7b8229739010f1cf7e7140184f0026bb3cbfb99116a8f1fe",
        "yosys.log": "54813f13acb695472ce71450f9f94d5a6118274c47332866cea1ed9b4271149f",
        "nextpnr.log": "8a161adaf61e8d97c25a7bacadcbcb82144ed8c0392e31445c0d8cec754c8fb0",
        "timing.txt": "47341676d69dd768b09e816679652101ec997dca651dfacdb90a3da8cad2c9ba",
    },
    "clean-build-2": {
        "SHA256SUMS": "cfe3dd6c384c54aedef2221263aa7b401ccf677e874e320b567a0359aaa515cf",
        "tool_versions.txt": "2e986e53019b3d9e7b8229739010f1cf7e7140184f0026bb3cbfb99116a8f1fe",
        "yosys.log": "a6ad59bf36b5acd48fe7448132d687730118a33c5181ff9185d7358d8e840028",
        "nextpnr.log": "2d01813e70101a4dfc7a376f8234c4a3d92007e6c97e0ea1b428fbaf579f65c2",
        "timing.txt": "47341676d69dd768b09e816679652101ec997dca651dfacdb90a3da8cad2c9ba",
    },
}


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(path: Path = RECEIPT) -> None:
    r = json.loads(path.read_text(encoding="utf-8"))
    require(r.get("schema") == "lean-silicon.lsc1-ulx3s-cleanroom-reproduction.v1", "schema")
    require(r.get("scoper") == "99f65947-0cdb-4d83-a569-d3bf3d1458ae", "scoper")
    require(r.get("base_commit") == BASE, "base commit")
    source = r.get("build_source", {})
    require(source == {"commit": SOURCE, "tree": "87462c2c698c43318df8b9a4db78c0c6ca9de251", "inputs_match_revision": True}, "source identity")
    tree = subprocess.check_output(["git", "rev-parse", f"{SOURCE}^{{tree}}"], cwd=ROOT, text=True).strip()
    require(tree == source["tree"], "source tree object")
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
    manifest = {line.split()[1]: line.split()[0] for line in (ARCHIVE / "SHA256SUMS").read_text().splitlines()}
    require(manifest == ARTIFACTS, "archived artifact manifest")
    for name, expected in ARTIFACTS.items():
        require(sha(ARCHIVE / name) == expected, f"archived hash {name}")
    runs = r.get("runs")
    require(isinstance(runs, list) and len(runs) == 2, "exactly two runs")
    require({x.get("id") for x in runs} == {"clean-build-1", "clean-build-2"}, "independent run identities")
    for run in runs:
        require(run.get("checkout") == "independent detached worktree", "isolated checkout")
        require(run.get("pre_build_tracked_clean") is True, "clean checkout")
        require(run.get("exit_code") == 0, "normal exit")
        require(run.get("source_manifest_sha256") == "bd86d1c1b265d4ee34d4aa152b7a86cba6cea36b2fde3d29bc48e3852e5f8f81", "complete source manifest")
        require(run.get("artifact_manifest_complete") is True, "complete artifact manifest")
        require(run.get("program_finished_normally") is True, "nextpnr completion")
        require(run.get("core_clock_pass") is True and run.get("achieved_core_clock_mhz", 0) >= 10.0, "10 MHz timing")
        require(run.get("raw_receipt_sha256") == RAW_RECEIPTS[run["id"]], "raw receipt hashes")
        require(run.get("artifacts") == ARTIFACTS, "run artifact hashes")
    require(r.get("conclusion") == "two clean host builds reproduced the archived packet bitstream artifacts byte-for-byte", "conclusion")


def main() -> int:
    try:
        verify()
    except (ValueError, KeyError, json.JSONDecodeError, OSError, subprocess.CalledProcessError) as error:
        print(f"FAIL reproduction receipt: {error}", file=sys.stderr)
        return 1
    print("PASS two-run clean-room ULX3S LSC-1 host-build reproduction")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

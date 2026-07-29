#!/usr/bin/env python3
"""Reject stale active integration names and verify LSC-1 declared sources."""
from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = [ROOT / "README.md", ROOT / "info.yaml", ROOT / "Makefile",
          ROOT / "docs", ROOT / "asic_core", ROOT / "fpga_harness", ROOT / "planning"]
OLD_TOP = "tt_um_leanvm_b_mincore"

def files():
    for item in ACTIVE:
        if item.is_file():
            yield item
        elif item.exists():
            yield from (p for p in item.rglob("*") if p.is_file())

def main():
    info = yaml.safe_load((ROOT / "info.yaml").read_text())
    if info["project"]["top_module"] != "tt_um_lfglabs_lean_silicon_lsc1":
        raise SystemExit("info.yaml must name tt_um_lfglabs_lean_silicon_lsc1")
    for source in info["project"]["source_files"]:
        path = ROOT / "src" / source
        if not path.is_file():
            raise SystemExit(f"missing declared ASIC source: {source}")
    wrapper = ROOT / "src/tt_um_lfglabs_lean_silicon_lsc1.sv"
    if not re.search(r"module\s+tt_um_lfglabs_lean_silicon_lsc1\b",
                     wrapper.read_text()):
        raise SystemExit("Tiny Tapeout integration wrapper missing")
    top = ROOT / "asic_core/rtl/lean_silicon_lsc1.sv"
    if not re.search(r"module\s+lean_silicon_lsc1\b", top.read_text()):
        raise SystemExit("LSC-1 Tiny Tapeout top missing")
    for path in files():
        if OLD_TOP in path.read_text(errors="ignore"):
            raise SystemExit(f"stale active top name in {path.relative_to(ROOT)}")
    protocol = (ROOT / "docs/LSC1_PROTOCOL.md").read_text()
    for required in ("version=1", "seed-0", "0xa1", "0x5a"):
        if required not in protocol:
            raise SystemExit(f"packet protocol marker missing: {required}")
    print("LSC-1 repository consistency: OK")

if __name__ == "__main__":
    main()

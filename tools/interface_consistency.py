#!/usr/bin/env python3
"""Cross-check protocol constants and Tiny Tapeout metadata across artifacts."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RTL = (ROOT / "asic_core" / "rtl" / "leanvm_b_stream_alu.sv").read_text()
PYMODEL = (ROOT / "sim" / "model.py").read_text()
WRAPPER = (ROOT / "asic_core" / "rtl" / "lean_silicon_lsc1.sv").read_text()
INFO = yaml.safe_load((ROOT / "info.yaml").read_text())

EXPECTED = {
    "CMD_XOR128": ("XOR128", 0x01),
    "CMD_MUL128": ("MUL128", 0x02),
    "CMD_SET128": ("SET128", 0x03),
    "CMD_NONZERO": ("NONZERO", 0x04),
    "CMD_CLEAR": ("CLEAR", 0x7D),
    "CMD_STATUS": ("STATUS", 0x7E),
}


def sv_constant(name: str) -> int:
    match = re.search(rf"localparam\s+\[7:0\]\s+{name}\s*=\s*8'h([0-9a-fA-F]{{2}})", RTL)
    if not match:
        raise SystemExit(f"missing SystemVerilog constant {name}")
    return int(match.group(1), 16)


def py_constant(name: str) -> int:
    match = re.search(rf"^\s*{name}\s*=\s*0x([0-9a-fA-F]+)\s*$", PYMODEL, re.MULTILINE)
    if not match:
        raise SystemExit(f"missing Python command constant {name}")
    return int(match.group(1), 16)


def main() -> None:
    for sv_name, (py_name, value) in EXPECTED.items():
        actual_sv = sv_constant(sv_name)
        actual_py = py_constant(py_name)
        if actual_sv != value or actual_py != value:
            raise SystemExit(
                f"command drift for {sv_name}/{py_name}: "
                f"RTL={actual_sv:#04x}, Python={actual_py:#04x}, expected={value:#04x}"
            )

    expected_status = "01 01 0f 08"
    if "bytes((0x01, 0x01, 0x0F, 0x08))" not in PYMODEL:
        raise SystemExit("Python status signature drifted")
    for literal in ("8'h01", "8'h0f", "8'h08"):
        if literal not in RTL:
            raise SystemExit(f"RTL status literal {literal} missing")

    project = INFO["project"]
    top = project["top_module"]
    if not re.search(rf"\bmodule\s+{re.escape(top)}\b", WRAPPER):
        raise SystemExit(f"info.yaml top module {top!r} is not present in wrapper")
    if project["clock_hz"] != 25_000_000:
        raise SystemExit("unexpected clock_hz")
    for source in project["source_files"]:
        if not (ROOT / source).is_file():
            raise SystemExit(f"missing Tiny Tapeout source file: {source}")

    print("Interface constants agree across RTL, Python, and info.yaml")
    print(f"  commands: {len(EXPECTED)}")
    print(f"  status:   {expected_status}")
    print(f"  top:      {top}")
    print(f"  sources:  {len(project['source_files'])}")


if __name__ == "__main__":
    main()

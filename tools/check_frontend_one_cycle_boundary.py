#!/usr/bin/env python3
"""Mechanical guard for the bounded frontend one-cycle correspondence slice."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "asic_core/rtl/lsc1_packet_frontend.sv"
FORMAL = ROOT / "formal/lsc1_packet_frontend_one_cycle_boundary.sv"

rtl = RTL.read_text()
formal = FORMAL.read_text()
required = (
    "arch_result_pending", "arch_staged_txn_id", "arch_staged_next_pc",
    "arch_staged_next_fp", "arch_staged_result_crc", "arch_state_valid",
    "arch_committed_pc", "arch_committed_fp", "arch_retire_seq",
    "arch_active_profile", "arch_last_status", "arch_last_fault",
)
missing = [name for name in required if name not in formal]
if missing:
    raise SystemExit(f"one-cycle relation omits retained frontend state: {missing}")
for good, bad in (
    ("result_pending <= 1'b0;\n            fault <= 1'b1;", "result_pending <= 1'b1;\n            fault <= 1'b1;"),
    ("last_status <= 8'h93;", "last_status <= 8'h00;"),
):
    if good not in rtl:
        raise SystemExit(f"expected transition target absent: {good!r}")
    if bad in rtl:
        raise SystemExit(f"abort next-state mutation survived: {bad!r}")
print("one-cycle boundary: retained frontend abort and quiescent-stutter state is covered")

#!/usr/bin/env python3
"""Check and report explicit sequential state in the MinCore arithmetic block.

This is intentionally a source-architecture count, not a mapped-cell estimate.
The script verifies that the expected declarations still exist before emitting
the total, so the MinCore design-space documentation cannot silently drift
after an RTL refactor.  It is not a count of the packet frontend or of the
complete ``lean_silicon_lsc1`` source closure.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src" / "leanvm_b_stream_alu.sv"
MULTIPLIER = ROOT / "src" / "gf2n_mul_bitstream.sv"

COMPONENTS = [
    ("FSM state", 4, ENGINE, r"reg\s+\[3:0\]\s+state\s*;"),
    ("byte index", 4, ENGINE, r"reg\s+\[3:0\]\s+byte_index\s*;"),
    ("shared scratch", 8, ENGINE, r"reg\s+\[7:0\]\s+scratch_byte\s*;"),
    ("sticky fault", 1, ENGINE, r"output\s+reg\s+fault"),
    ("shifted multiplicand", 128, MULTIPLIER, r"reg\s+\[WIDTH-1:0\]\s+a_shift\s*;"),
    ("accumulator", 128, MULTIPLIER, r"reg\s+\[WIDTH-1:0\]\s+accumulator\s*;"),
]


def main() -> None:
    for name, _, path, pattern in COMPONENTS:
        text = path.read_text()
        if not re.search(pattern, text):
            raise SystemExit(f"state declaration for {name!r} not found in {path}")

    total = sum(bits for _, bits, _, _ in COMPONENTS)
    print("Explicit source-level sequential state (MinCore arithmetic only)")
    for name, bits, _, _ in COMPONENTS:
        print(f"  {name:24s} {bits:3d} bits")
    print(f"  {'TOTAL':24s} {total:3d} bits")
    if total != 273:
        raise SystemExit(
            f"unexpected MinCore arithmetic total {total}; "
            "design-space documentation assumes 273"
        )


if __name__ == "__main__":
    main()

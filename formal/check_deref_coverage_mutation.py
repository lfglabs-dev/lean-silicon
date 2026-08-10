#!/usr/bin/env python3
"""Prove that the cycle immediately below the derived trace is unreached."""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "full_lsc1_deref_bridge.sby"
MUTANT = HERE / ".full_lsc1_deref_bridge_below_bound_mutation.sby"


def main() -> int:
    text = SOURCE.read_text()
    anchor = "reachability: depth 2788"
    if text.count(anchor) != 1:
        raise SystemExit(f"expected one {anchor!r} anchor")
    MUTANT.write_text(text.replace(anchor, "reachability: depth 2787"))
    try:
        result = subprocess.run(
            ["sby", "-f", MUTANT.name, "reachability"],
            cwd=HERE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=12600,
        )
    finally:
        MUTANT.unlink(missing_ok=True)
        shutil.rmtree(HERE / ".full_lsc1_deref_bridge_below_bound_mutation", ignore_errors=True)
        shutil.rmtree(HERE / ".full_lsc1_deref_bridge_below_bound_mutation_reachability", ignore_errors=True)

    rejected = result.returncode != 0 and "Unreached cover statement" in result.stdout
    print("below_first_reachable_bound_rejected=" + str(rejected).lower())
    if not rejected:
        print(result.stdout)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

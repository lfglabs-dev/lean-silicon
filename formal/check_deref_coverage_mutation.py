#!/usr/bin/env python3
"""Prove that the cycle immediately below the derived trace is unreached."""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

from subprocess_tree import run_bounded


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "full_lsc1_deref_bridge.sby"
MUTANT = HERE / ".full_lsc1_deref_bridge_below_bound_mutation.sby"
SOLVER_TIMEOUT_SECONDS = 3600


def main() -> int:
    text = SOURCE.read_text()
    anchor = "reachability: depth 2788"
    if text.count(anchor) != 1:
        raise SystemExit(f"expected one {anchor!r} anchor")
    MUTANT.write_text(text.replace(anchor, "reachability: depth 2787"))
    try:
        result = run_bounded(
            ["sby", "-f", MUTANT.name, "reachability"],
            cwd=HERE,
            timeout=SOLVER_TIMEOUT_SECONDS,
        )
    finally:
        MUTANT.unlink(missing_ok=True)
        shutil.rmtree(HERE / ".full_lsc1_deref_bridge_below_bound_mutation", ignore_errors=True)
        shutil.rmtree(HERE / ".full_lsc1_deref_bridge_below_bound_mutation_reachability", ignore_errors=True)

    output = result.stdout.lower()
    # An unreached cover is a completed SBY FAIL. Engines differ in whether
    # they also print the legacy "Unreached cover statement" diagnostic.
    rejected = result.returncode != 0 and "done (fail, rc=2)" in output
    print("below_first_reachable_bound_rejected=" + str(rejected).lower())
    if not rejected:
        print(result.stdout)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Prove each lifecycle checkpoint is non-vacuous at its exact first bound."""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

from subprocess_tree import run_bounded


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "full_lsc1_deref_bridge.sby"
MUTANT = HERE / ".full_lsc1_deref_bridge_below_bound_mutation.sby"
SOLVER_TIMEOUT_SECONDS = 540
CHECKPOINTS = [
    ("accepted_result_reachability", 2767),
    ("matching_retire_reachability", 2786),
    ("reachability", 2788),
]


def main() -> int:
    source_text = SOURCE.read_text()
    for task, depth in CHECKPOINTS:
        anchor = f"{task}: depth {depth}"
        if source_text.count(anchor) != 1:
            raise SystemExit(f"expected one {anchor!r} anchor")
        MUTANT.write_text(source_text.replace(anchor, f"{task}: depth {depth - 1}"))
        try:
            result = run_bounded(
                ["sby", "-f", MUTANT.name, task], cwd=HERE,
                timeout=SOLVER_TIMEOUT_SECONDS,
            )
        finally:
            MUTANT.unlink(missing_ok=True)
            shutil.rmtree(HERE / ".full_lsc1_deref_bridge_below_bound_mutation", ignore_errors=True)
            shutil.rmtree(HERE / f".full_lsc1_deref_bridge_below_bound_mutation_{task}", ignore_errors=True)
        output = result.stdout.lower()
        rejected = result.returncode != 0 and "done (fail, rc=2)" in output
        print(f"{task}: below_first_reachable_bound_rejected={str(rejected).lower()}")
        if not rejected:
            print(result.stdout)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

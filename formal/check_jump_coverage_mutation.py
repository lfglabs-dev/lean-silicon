#!/usr/bin/env python3
"""Reject every JUMP lifecycle cover exactly one step below its first bound."""

import shutil
from pathlib import Path

try:
    from formal.subprocess_tree import run_bounded
except ModuleNotFoundError:
    from subprocess_tree import run_bounded

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "full_lsc1_jump_bridge.sby"
MUTANT = HERE / ".full_lsc1_jump_below_bound.sby"
CHECKPOINTS = [
    ("accepted_result_reachability", 5571),
    ("matching_retire_reachability", 5591),
    ("reachability", 5592),
]


def main() -> int:
    text = SOURCE.read_text()
    for task, depth in CHECKPOINTS:
        anchor = f"{task}: depth {depth}"
        if text.count(anchor) != 1:
            raise SystemExit(f"expected one {anchor!r} anchor")
        MUTANT.write_text(text.replace(anchor, f"{task}: depth {depth - 1}"))
        try:
            result = run_bounded(
                ["sby", "-f", MUTANT.name, task], cwd=HERE, timeout=540,
            )
        finally:
            MUTANT.unlink(missing_ok=True)
            shutil.rmtree(HERE / f".full_lsc1_jump_below_bound_{task}", ignore_errors=True)
        rejected = result.returncode != 0 and "done (fail, rc=2)" in result.stdout.lower()
        print(f"{task}: below_first_reachable_bound_rejected={str(rejected).lower()}")
        if not rejected:
            print(result.stdout)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

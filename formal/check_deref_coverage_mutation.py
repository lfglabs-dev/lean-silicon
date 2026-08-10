#!/usr/bin/env python3
"""Prove that restoring the old depth-20 cover bound is rejected."""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "full_lsc1_deref_bridge.sby"
MUTANT = HERE / ".full_lsc1_deref_bridge_depth20_mutation.sby"


def main() -> int:
    text = SOURCE.read_text()
    anchor = "reachability: depth 97"
    if text.count(anchor) != 1:
        raise SystemExit(f"expected one {anchor!r} anchor")
    MUTANT.write_text(text.replace(anchor, "reachability: depth 20"))
    try:
        result = subprocess.run(
            ["sby", "-f", MUTANT.name, "reachability"],
            cwd=HERE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    finally:
        MUTANT.unlink(missing_ok=True)
        shutil.rmtree(HERE / ".full_lsc1_deref_bridge_depth20_mutation", ignore_errors=True)
        shutil.rmtree(HERE / ".full_lsc1_deref_bridge_depth20_mutation_reachability", ignore_errors=True)

    rejected = result.returncode != 0 and "Unreached cover statement" in result.stdout
    print("depth20_cover_mutation_rejected=" + str(rejected).lower())
    if not rejected:
        print(result.stdout)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

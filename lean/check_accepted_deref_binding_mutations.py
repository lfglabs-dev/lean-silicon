#!/usr/bin/env python3
"""Require both accepted-frame premises in the accepted DEREF theorem proof."""

from pathlib import Path
import os
import subprocess
import tempfile


source = Path(__file__).with_name("LeanVMBMinCore") / "AcceptedDeref.lean"
text = source.read_text()
anchor = "simp only [haccept, Except.map, heffect]"
if text.count(anchor) != 1:
    raise SystemExit(f"expected exactly one proof anchor {anchor!r}")

mutations = {
    "drops-accepted-frame-binding": "simp only [Except.map, heffect]",
    "drops-successful-decision-binding": "simp only [haccept, Except.map]",
}

for name, replacement in mutations.items():
    mutated = text.replace(anchor, replacement, 1)
    with tempfile.TemporaryDirectory(prefix="lsc1-accepted-deref-mutation-") as directory:
        candidate = Path(directory) / "AcceptedDeref.lean"
        candidate.write_text(mutated)
        result = subprocess.run(
            ["lake", "env", "lean", str(candidate)],
            cwd=source.parent.parent,
            env=os.environ,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if result.returncode == 0:
        raise SystemExit(f"SURVIVED: {name}")
    print(f"KILLED: {name}")

#!/usr/bin/env python3
"""Require both accepted-frame premises in the scalar lifecycle theorem."""

from pathlib import Path
import os
import subprocess
import tempfile

source = Path(__file__).with_name("LeanVMBMinCore") / "AcceptedScalar.lean"
text = source.read_text()
anchor = "simp only [haccept, Except.map, heffect]"
mutations = {
    "drops-accepted-frame-binding": "simp only [Except.map, heffect]",
    "drops-successful-decision-binding": "simp only [haccept, Except.map]",
}
if text.count(anchor) != 1:
    raise SystemExit(f"expected exactly one proof anchor {anchor!r}")
for name, replacement in mutations.items():
    with tempfile.TemporaryDirectory(prefix="lsc1-accepted-scalar-mutation-") as directory:
        candidate = Path(directory) / "AcceptedScalar.lean"
        candidate.write_text(text.replace(anchor, replacement, 1))
        result = subprocess.run(
            ["lake", "env", "lean", str(candidate)], cwd=source.parent.parent,
            env=os.environ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, check=False,
        )
    if result.returncode == 0:
        raise SystemExit(f"SURVIVED: {name}")
    print(f"KILLED: {name}")

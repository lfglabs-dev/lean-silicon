#!/usr/bin/env python3
"""Require the canonical full-profile bridge to detect semantic mutations."""

from pathlib import Path
import os
import subprocess
import tempfile

source = Path(__file__).with_name("LeanVMBMinCore") / "FullProfile.lean"
text = source.read_text()

mutations = {
    "mul-becomes-xor": (
        "(GHASH128.mul (input.memory input.left).value (input.memory input.right).value)",
        "((input.memory input.left).value ^^^ (input.memory input.right).value)",
    ),
    "blake3-bypasses-service": (
        "| .blake3 request => .serviceRequired request",
        "| .blake3 request => .fault .badService",
    ),
    "stages-accepts-rejection": (
        "outcome.model.state = .resultPending (transitionOf effect)",
        "outcome.model.state = .idle",
    ),
}

for name, (old, new) in mutations.items():
    if text.count(old) < 2 and name == "mul-becomes-xor":
        raise SystemExit(f"mutation anchor changed: {name}")
    if old not in text:
        raise SystemExit(f"mutation anchor missing: {name}")
    mutated = text.replace(old, new, 1)
    with tempfile.TemporaryDirectory(prefix="lsc1-lean-mutation-") as directory:
        candidate = Path(directory) / "FullProfile.lean"
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

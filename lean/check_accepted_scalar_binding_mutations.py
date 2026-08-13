#!/usr/bin/env python3
"""Require scalar lifecycle proofs to bind encoded request fields through accept."""

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

# Compile decoder mutations in an isolated workspace.  Each mutation still
# returns a successfully decoded request, but disconnects a concrete encoded
# field from the Accepted value.  The encoded-wire reachability theorems above
# must therefore stop elaborating.
payload_source = source.with_name("FullProfilePayload.lean")
payload_text = payload_source.read_text()
decoder_mutations = {
    "set-output-offset-reads-constant": (
        "outputOffset := natLE bytes 14 4\n    constant := wordAt bytes 18",
        "outputOffset := natLE bytes 18 4\n    constant := wordAt bytes 18",
    ),
    "binary-left-offset-reads-right-offset": (
        "leftOffset := natLE bytes 14 4\n    rightOffset := natLE bytes 18 4",
        "leftOffset := natLE bytes 18 4\n    rightOffset := natLE bytes 18 4",
    ),
    "binary-right-cell-reads-left-cell": (
        "leftCell := left, rightCell := right, outputCell := output",
        "leftCell := left, rightCell := left, outputCell := output",
    ),
}
lean_root = source.parent.parent
for name, (old, new) in decoder_mutations.items():
    if payload_text.count(old) != 1:
        raise SystemExit(f"expected exactly one decoder anchor for {name}")
    with tempfile.TemporaryDirectory(prefix="lsc1-accepted-scalar-decoder-mutation-") as directory:
        candidate_root = Path(directory) / "lean"
        subprocess.run(
            ["cp", "-a", str(lean_root), str(candidate_root)],
            check=True,
        )
        candidate_payload = candidate_root / "LeanVMBMinCore" / "FullProfilePayload.lean"
        candidate_payload.write_text(payload_text.replace(old, new, 1))
        result = subprocess.run(
            ["lake", "build", "LeanVMBMinCore"], cwd=candidate_root,
            env=os.environ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, check=False,
        )
    if result.returncode == 0:
        raise SystemExit(f"SURVIVED: {name}")
    print(f"KILLED: {name}")

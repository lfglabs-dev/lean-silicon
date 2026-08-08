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
        "GHASH128.mul (memory input.left).value (memory input.right).value",
        "(memory input.left).value ^^^ (memory input.right).value",
    ),
    "blake3-bypasses-service": (
        "| some nextControl => .serviceRequired { request, nextControl }",
        "| some nextControl => .fault .badService",
    ),
    "stages-accepts-rejection": (
        "outcome.model.state = .resultPending (transitionOf effect)",
        "outcome.model.state = .idle",
    ),
    "blake3-unchecked-first-write": (
        "match writeOnce request.memory request.outputAddresses.1 response.digest.1 with",
        "match some (writeRaw request.memory request.outputAddresses.1 response.digest.1) with",
    ),
    "pc-overflow-becomes-write-conflict": (
        "| none => .fault .address\n  | some next =>",
        "| none => .fault .writeConflict\n  | some next =>",
    ),
    "deref-bypasses-control-binding": (
        "if input.prepared.control != input.common.control then",
        "if false then",
    ),
    "jump-drops-host-memory": (
        "common := input.common, nextControl := control, memory := input.memory",
        "common := input.common, nextControl := control, memory := Memory.empty",
    ),
    "forward-only-allows-missing-operands": (
        "if input.profile == .forwardOnly && (leftAbsent || rightAbsent) then",
        "if false then",
    ),
    "mul-accepts-absent-inverse": (
        "else if !input.proposedInverse.written ||",
        "else if false ||",
    ),
    "xor-skips-backsolve": (
        "let backsolve := (input.memory input.output).written && (leftAbsent != rightAbsent)",
        "let backsolve := false",
    ),
    "blake3-suspends-on-pc-overflow": (
        "| none => .fault .address\n      | some nextControl => .serviceRequired { request, nextControl }",
        "| none => .serviceRequired { request, nextControl := request.common.control }\n      | some nextControl => .serviceRequired { request, nextControl }",
    ),
    "blake3-response-remains-replayable": (
        "| .pending pending, .respond response => {\n      state := .idle, decision := some (finishBlake3 pending response) }",
        "| .pending pending, .respond response => {\n      state := .pending pending, decision := some (finishBlake3 pending response) }",
    ),
}

for name, (old, new) in mutations.items():
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

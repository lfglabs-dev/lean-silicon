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
    "write-conflict-loses-to-pc-overflow": (
        "match writeOnce memory address value with\n  | none => .fault .writeConflict",
        "match writeOnce memory address value with\n  | none => .fault .address",
    ),
    "blake3-ignores-service-kind": (
        "response.serviceKind != 1 then",
        "false then",
    ),
    "bridge-uses-u32-index-bound": (
        "def protocolIndexLimit : Nat := 2 ^ 16",
        "def protocolIndexLimit : Nat := 2 ^ 32",
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
        "state := .idle nextServiceId, decision := some (finishBlake3 pending response)",
        "state := .pending nextServiceId pending, decision := some (finishBlake3 pending response)",
    ),
    "blake3-service-id-is-caller-owned": (
        "let assigned := start.assignServiceId nextServiceId",
        "let assigned := start.assignServiceId 0",
    ),
    "blake3-reset-reuses-service-id": (
        "| .pending _ _, .reset => { state := .idle 1 }",
        "| .pending _ _, .reset => { state := .idle 2 }",
    ),
    "blake3-allows-three-message-words": (
        "inputWords : Fin 4 -> Word",
        "inputWords : Fin 3 -> Word",
    ),
    "forward-only-deref-copies-missing-local": (
        "else if mode == .cell && input.profile == .forwardOnly &&",
        "else if false && input.profile == .forwardOnly &&",
    ),
    "blake3-mismatch-drops-pending": (
        "state := .pending nextServiceId pending, decision := some (.fault .badService)",
        "state := .idle nextServiceId, decision := some (.fault .badService)",
    ),
    "deref-profile-guard-precedes-pointer": (
        "else if !(input.memory input.prepared.pointerAddress).written ||",
        "else if false && !(input.memory input.prepared.pointerAddress).written ||",
    ),
    "blake3-accepts-malformed-metadata": (
        "if validBlake3Metadata raw.metadata then prepareValidBlake3 raw",
        "if true then prepareValidBlake3 raw",
    ),
    "blake3-second-output-reuses-first": (
        "match CheckedIndex.add out0 1 with",
        "match CheckedIndex.add out0 0 with",
    ),
    "blake3-response-drops-transaction-binding": (
        "response.txnId == pending.request.common.txnId &&",
        "true &&",
    ),
    "blake3-response-does-not-stage": (
        "let transaction := Transaction.step state.transaction\n                    (.stage (transitionOf effect))",
        "let transaction := Transaction.step state.transaction .abort",
    ),
    "blake3-reset-starts-at-two": (
        "state := endpointInitial",
        "state := { transaction := Transaction.initial, service := .idle 2 }",
    ),
    "blake3-id-overflow-wraps": (
        "nextServiceId == 0 || nextServiceId == 0xffffffff",
        "nextServiceId == 0 || false",
    ),
    "blake3-retire-never-commits": (
        "Transaction.step state.transaction (.retire txnId checksum)",
        "Transaction.step state.transaction .abort",
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

packet_source = source.with_name("FullProfilePacket.lean")
packet_text = packet_source.read_text()
packet_mutations = {
    "set-skips-address-check": (
        "match CheckedIndex.add packet.common.control.fp packet.outputOffset with",
        "match some (packet.common.control.fp + packet.outputOffset) with",
    ),
    "set-drops-supplied-cell": (
        ".set packet.common (putCell Memory.empty output packet.outputCell)",
        ".set packet.common Memory.empty",
    ),
    "set-bypasses-canonical-decision": (
        "| .ok instruction => decide instruction",
        "| .ok instruction => .fault .badInverse",
    ),
    "packet-skips-left-address-check": (
        "match CheckedIndex.add packet.common.control.fp packet.leftOffset with",
        "match some (packet.common.control.fp + packet.leftOffset) with",
    ),
    "packet-accepts-inconsistent-alias": (
        "if aliasConflict left right output packet.leftCell packet.rightCell",
        "if false && aliasConflict left right output packet.leftCell packet.rightCell",
    ),
    "packet-bypasses-binary-decision": (
        "| .ok input => finishBinary isXor input",
        "| .ok input => .fault .badInverse",
    ),
    "packet-drops-left-cell": (
        "putCell (putCell (putCell Memory.empty left packet.leftCell)",
        "putCell (putCell (putCell Memory.empty left packet.outputCell)",
    ),
}

for name, (old, new) in packet_mutations.items():
    if old not in packet_text:
        raise SystemExit(f"mutation anchor missing: {name}")
    mutated = packet_text.replace(old, new, 1)
    with tempfile.TemporaryDirectory(prefix="lsc1-lean-packet-mutation-") as directory:
        candidate = Path(directory) / "FullProfilePacket.lean"
        candidate.write_text(mutated)
        result = subprocess.run(
            ["lake", "env", "lean", str(candidate)],
            cwd=packet_source.parent.parent,
            env=os.environ,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if result.returncode == 0:
        raise SystemExit(f"SURVIVED: {name}")
    print(f"KILLED: {name}")

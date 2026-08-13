#!/usr/bin/env python3
"""Require the mixed-sequence theorem to observe result, retire, and loss mutations."""

from pathlib import Path
import os
import subprocess
import tempfile

source = Path(__file__).with_name("LeanVMBMinCore") / "AcceptedSequence.lean"
text = source.read_text()
mutations = {
    "result-payload-byte-loss": (
        "Packet.encodeResponse crc32 (resultResponse item)",
        "Packet.encodeResponse crc32 { status := 0, payload := [] }",
    ),
    "retire-checksum-mismatch": (
        "Transaction.step staged.model\n    (.retire (transition item).txnId (transition item).resultChecksum)",
        "Transaction.step staged.model\n    (.retire (transition item).txnId ((transition item).resultChecksum + 1))",
    ),
    "successful-retire-receipt-loss": (
        "if outcome.retired then receipt model item :: tail.2 else tail.2",
        "if false then receipt model item :: tail.2 else tail.2",
    ),
}

for name, (old, new) in mutations.items():
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one mutation anchor for {name}")
    with tempfile.TemporaryDirectory(prefix="lsc1-accepted-sequence-mutation-") as directory:
        candidate = Path(directory) / "AcceptedSequence.lean"
        candidate.write_text(text.replace(old, new, 1))
        result = subprocess.run(
            ["lake", "env", "lean", str(candidate)], cwd=source.parent.parent,
            env=os.environ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, check=False,
        )
    if result.returncode == 0:
        raise SystemExit(f"SURVIVED: {name}")
    print(f"KILLED: {name}")

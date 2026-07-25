#!/usr/bin/env python3
"""Generate or verify the checksum inventory for Git-tracked source artifacts.

Build products and arbitrary untracked files must never leak into a release
inventory.  Stage newly added files before generating the tracked SHA256SUMS.
"""
from hashlib import sha256
from pathlib import Path
from subprocess import check_output
import sys

ROOT = Path(__file__).resolve().parents[1]
TRACKED = check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
inventory = "".join(
    f"{sha256((ROOT / name).read_bytes()).hexdigest()}  ./{name}\n"
    for name in sorted(item.decode() for item in TRACKED if item and item != b"SHA256SUMS")
)

if sys.argv[1:] == ["--check"]:
    if (ROOT / "SHA256SUMS").read_text() != inventory:
        raise SystemExit("SHA256SUMS is stale; run `make checksums`")
    print("SHA256SUMS matches tracked source artifacts")
elif len(sys.argv) == 1:
    print(inventory, end="")
else:
    raise SystemExit("usage: generate_checksums.py [--check]")

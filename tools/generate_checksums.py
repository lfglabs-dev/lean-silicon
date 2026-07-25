#!/usr/bin/env python3
"""Generate the checksum inventory for Git-tracked source artifacts.

Build products and arbitrary untracked files must never leak into a release
inventory.  Stage newly added files before generating the tracked SHA256SUMS.
"""
from hashlib import sha256
from pathlib import Path
from subprocess import check_output

ROOT = Path(__file__).resolve().parents[1]
TRACKED = check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
for name in sorted(item.decode() for item in TRACKED if item and item != b"SHA256SUMS"):
    path = ROOT / name
    print(f"{sha256(path.read_bytes()).hexdigest()}  ./{name}")

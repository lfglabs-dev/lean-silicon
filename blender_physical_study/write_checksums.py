#!/usr/bin/env python3
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
paths = [
    *sorted((HERE / "artifacts").glob("*")),
    HERE / "provenance.json",
]
lines = []
for path in paths:
    if path.is_file():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(HERE)}")
(HERE / "SHA256SUMS").write_text("\n".join(lines) + "\n")

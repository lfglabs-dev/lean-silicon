#!/usr/bin/env python3
"""Independent structural contract for the production BLAKE pending implication."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def tokens(text: str) -> list[str]:
    """Return SystemVerilog tokens after removing comments and whitespace."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    return re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*|\d+'[bdhoBDHO][0-9a-fA-F_xXzZ]+|\S", text)


REQUIRED = [
    "always", "@", "(", "*", ")", "begin",
    "if", "(", "blake_result_pending", ")",
    "assert", "(", "result_pending", ")", ";",
]


def validate(text: str) -> tuple[bool, str]:
    stream = tokens(text)
    matches = sum(stream[index:index + len(REQUIRED)] == REQUIRED
                  for index in range(len(stream) - len(REQUIRED) + 1))
    if matches != 1:
        return False, f"production_blake_pending_implication_count={matches};expected=1"
    return True, "production_blake_pending_implication_present"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_blake3_pending_contract.py INVARIANT", file=sys.stderr)
        return 2
    path = Path(argv[1])
    valid, reason = validate(path.read_text())
    print(json.dumps({"contract_version": 1, "valid": valid, "reason": reason}, sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

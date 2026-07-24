#!/usr/bin/env python3
"""Small offline structural smoke check for SystemVerilog sources.

This is not a compiler. It removes comments/strings, checks delimiter balance,
and checks block-keyword nesting for the subset used by this project. It is
useful in restricted environments where Icarus/Verilator are unavailable.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TOKEN_RE = re.compile(r"\b(?:module|endmodule|function|endfunction|case|endcase|begin|end)\b|[(){}\[\]]")
PAIR = {')': '(', '}': '{', ']': '['}
OPEN_BLOCK = {'module': 'endmodule', 'function': 'endfunction', 'case': 'endcase', 'begin': 'end'}
CLOSE_BLOCK = {v: k for k, v in OPEN_BLOCK.items()}


def strip(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    return text


def check(path: Path) -> list[str]:
    text = strip(path.read_text())
    delimiters: list[tuple[str, int]] = []
    blocks: list[tuple[str, int]] = []
    errors: list[str] = []
    for match in TOKEN_RE.finditer(text):
        tok = match.group(0)
        line = text.count('\n', 0, match.start()) + 1
        if tok in '({[':
            delimiters.append((tok, line))
        elif tok in ')}]':
            if not delimiters or delimiters[-1][0] != PAIR[tok]:
                errors.append(f"line {line}: unmatched {tok}")
            else:
                delimiters.pop()
        elif tok in OPEN_BLOCK:
            blocks.append((tok, line))
        else:
            expected_open = CLOSE_BLOCK[tok]
            if not blocks or blocks[-1][0] != expected_open:
                got = blocks[-1][0] if blocks else '<empty>'
                errors.append(f"line {line}: {tok} closes {got}, expected {expected_open}")
            else:
                blocks.pop()
    errors.extend(f"line {line}: unclosed {tok}" for tok, line in reversed(delimiters))
    errors.extend(f"line {line}: unclosed {tok}" for tok, line in reversed(blocks))
    return errors


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv[1:]]
    if not paths:
        paths = sorted((Path(__file__).resolve().parents[1] / 'src').glob('*.sv'))
    failed = False
    for path in paths:
        errors = check(path)
        if errors:
            failed = True
            print(f"{path}: FAIL")
            for e in errors:
                print(f"  {e}")
        else:
            print(f"{path}: structurally balanced")
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))

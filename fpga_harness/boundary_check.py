#!/usr/bin/env python3
"""Check that the harness boundary stays the exact narrow ASIC pin interface.

Every compatibility byte must cross the LSC-1 8-bit ready/valid pins, so this
script fails on the two ways that rule gets broken in practice: a harness port
wider than the pin interface (a wide bypass), and an ASIC top that drives a pin
the direction mask declares an input.

Role names come from ``info.yaml`` and ``docs/LSC1_PROTOCOL.md``, which belong
to other lanes.  This checker only reads them.  It hard-fails on objective,
structural violations and reports unrecognised driven signals as observations,
so that renaming an internal RTL signal in another lane cannot turn this into a
false tripwire.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import yaml

ROOT = Path(__file__).resolve().parents[1]
ASIC_TOP = ROOT / "asic_core" / "rtl" / "lean_silicon_lsc1.sv"
HARNESS_RTL_DIR = ROOT / "fpga_harness" / "rtl"
INFO_YAML = ROOT / "info.yaml"
PROTOCOL_DOC = ROOT / "docs" / "LSC1_PROTOCOL.md"

PIN_WIDTH = 8
RTL_SUFFIXES = (".sv", ".v")
# Direction mask published by the ASIC top and the protocol contract: bit set
# means the ASIC drives that uio pin.
EXPECTED_UIO_OE = 0b10110110

# Substring fingerprints for the roles the ASIC drives, used only to attribute
# a driven bit to a documented role. Unknown names are observations, not errors.
DRIVEN_ROLE_HINTS = {
    "RX_READY": "rx_ready",
    "TX_VALID": "tx_valid",
    "BUSY": "busy",
    "FAULT": "fault",
    "DONE_PULSE": "done",
}


@dataclass
class Result:
    errors: list[str]
    observations: list[str]
    facts: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_abbreviation(first: str, second: str) -> bool:
    """True when one role name is a leading-token abbreviation of the other."""
    left, right = first.split("_"), second.split("_")
    shorter, longer = sorted((left, right), key=len)
    return longer[: len(shorter)] == shorter


def _uio_roles_from_info() -> dict[int, str]:
    info = yaml.safe_load(INFO_YAML.read_text())
    roles: dict[int, str] = {}
    for key, value in info["pinout"].items():
        match = re.fullmatch(r"uio\[(\d)\]", str(key))
        if match:
            roles[int(match.group(1))] = str(value).strip()
    return roles


def _uio_roles_from_protocol() -> dict[int, str]:
    text = PROTOCOL_DOC.read_text()
    roles: dict[int, str] = {}
    for index, name in re.findall(r"`?uio\[(\d)\]\s*=\s*([A-Z0-9_]+)", text):
        roles[int(index)] = name
    # The contract abbreviates later entries as `[n]=NAME` after the first.
    for index, name in re.findall(r"`?\[(\d)\]\s*=\s*([A-Z0-9_]+)", text):
        roles.setdefault(int(index), name)
    return roles


def _declared_oe(text: str) -> int | None:
    match = re.search(r"assign\s+uio_oe\s*=\s*8'b([01]{8})", text)
    if match:
        return int(match.group(1), 2)
    match = re.search(r"assign\s+uio_oe\s*=\s*8'h([0-9a-fA-F]{2})", text)
    return int(match.group(1), 16) if match else None


def _uio_out_terms(text: str) -> list[str] | None:
    """Return the uio_out concat terms ordered MSB..LSB (index 7..0)."""
    match = re.search(r"assign\s+uio_out\s*=\s*\{([^}]*)\}\s*;", text, re.DOTALL)
    if not match:
        return None
    terms = [term.strip() for term in match.group(1).split(",")]
    return terms if len(terms) == PIN_WIDTH else None


def _is_literal_zero(term: str) -> bool:
    return re.fullmatch(r"(1'b0|1'h0|1'd0|0)", term) is not None


_DIRECTION_RE = re.compile(r"\b(?:input|output|inout)\b")
# An item of a declaration group: the type and packed dimensions, the name, and
# any unpacked dimensions after it. Every dimension group counts towards the
# width, so neither ``[7:0][3:0]`` nor ``[7:0] bytes [15:0]`` can present 128
# bits as 8.
_PORT_ITEM_RE = re.compile(r"^(.*?)([A-Za-z_]\w*)\s*((?:\[[^\]]*\]\s*)*)$", re.DOTALL)
_ONE_RANGE_RE = re.compile(r"\[([^\]]*)\]")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][\w$]*(?:\s*::\s*[A-Za-z_][\w$]*)*")

# Net kinds and modifiers that carry no width of their own; a port declared with
# only these is one bit before dimensions are applied.
_WIDTHLESS_KEYWORDS = frozenset(
    {
        "var", "signed", "unsigned", "const", "automatic", "static", "ref",
        "wire", "reg", "logic", "bit", "tri", "tri0", "tri1", "triand",
        "trior", "trireg", "wand", "wor", "supply0", "supply1", "uwire",
    }
)
# Built-in types whose width is implicit: no bracket range appears, so without
# this table ``output integer bypass`` would be scored as a single bit.
_IMPLICIT_TYPE_WIDTHS = {
    "byte": 8, "shortint": 16, "int": 32, "integer": 32, "longint": 64,
    "time": 64, "shortreal": 32, "real": 64, "realtime": 64,
}
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def _strip_comments(text: str) -> str:
    """Remove Verilog comments so stale commented-out code cannot mask drift."""
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", text))
_PARAM_RE = re.compile(
    r"\b(?:parameter|localparam)\b[^;=]*?(\w+)\s*=\s*([^,;)]+)"
)


def _eval_const(node: ast.AST, bindings: dict[str, int]) -> int | None:
    """Evaluate a whitelisted integer expression; None when not constant."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, int) else None
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.UnaryOp):
        value = _eval_const(node.operand, bindings)
        if value is None:
            return None
        if isinstance(node.op, ast.USub):
            return -value
        return value if isinstance(node.op, ast.UAdd) else None
    if isinstance(node, ast.BinOp):
        left = _eval_const(node.left, bindings)
        right = _eval_const(node.right, bindings)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.FloorDiv) and right != 0:
            return left // right
        return None
    return None


def _const_value(text: str, bindings: dict[str, int]) -> int | None:
    candidate = text.strip()
    sized = re.fullmatch(r"\d*'[sSdD]?[dD]?(\d+)", candidate)
    if sized:
        return int(sized.group(1))
    try:
        tree = ast.parse(candidate, mode="eval")
    except SyntaxError:
        return None
    return _eval_const(tree.body, bindings)


def _constant_bindings(text: str) -> dict[str, int]:
    """Resolve local parameters, including ones defined in terms of others."""
    raw = {name: value for name, value in _PARAM_RE.findall(text)}
    bindings: dict[str, int] = {}
    for _pass in range(len(raw) + 1):
        progressed = False
        for name, value in raw.items():
            if name in bindings:
                continue
            resolved = _const_value(value, bindings)
            if resolved is not None:
                bindings[name] = resolved
                progressed = True
        if not progressed:
            break
    return bindings


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are not inside brackets."""
    items: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            items.append(text[start:index])
            start = index + 1
    items.append(text[start:])
    return items


def _declaration_groups(text: str) -> list[str]:
    """Text governed by each direction keyword, up to the end of its list.

    A group runs to the closing paren or semicolon, so every name after a comma
    stays with the direction that introduced it and cannot escape the scan.
    """
    groups: list[str] = []
    for match in _DIRECTION_RE.finditer(text):
        start = match.end()
        depth = 0
        end = len(text)
        for index in range(start, len(text)):
            char = text[index]
            if char in "([{":
                depth += 1
            elif char in ")]}":
                if depth == 0:
                    end = index
                    break
                depth -= 1
            elif char == ";" and depth == 0:
                end = index
                break
        following = _DIRECTION_RE.search(text, start)
        if following is not None and following.start() < end:
            end = following.start()
        groups.append(text[start:end])
    return groups


def _base_width(prefix: str) -> tuple[int | None, str | None]:
    """Width implied by a port's data type, or the token that defeated us."""
    width = 1
    for match in _IDENTIFIER_RE.finditer(_ONE_RANGE_RE.sub(" ", prefix)):
        token = re.sub(r"\s+", "", match.group(0))
        if token in _WIDTHLESS_KEYWORDS:
            continue
        if token in _IMPLICIT_TYPE_WIDTHS:
            width = _IMPLICIT_TYPE_WIDTHS[token]
            continue
        return None, token
    return width, None


def _dimension_factor(bounds: str, params: dict[str, int]) -> int | None:
    """Number of bits a single ``[...]`` contributes, or None if unresolvable."""
    if ":" in bounds:
        high_text, low_text = bounds.split(":", 1)
        high = _const_value(high_text, params)
        low = _const_value(low_text, params)
        if high is None or low is None:
            return None
        return abs(high - low) + 1
    size = _const_value(bounds, params)
    return None if size is None else abs(size)


def _port_widths(text: str) -> list[tuple[str, int | None, str]]:
    """Every declared port as (name, width, detail); width None means unresolved."""
    params = _constant_bindings(text)
    ports: list[tuple[str, int | None, str]] = []
    for group in _declaration_groups(text):
        inherited: str | None = None
        for item in _split_top_level(group):
            match = _PORT_ITEM_RE.match(item.strip())
            if match is None:
                continue
            prefix, name, unpacked = match.groups()
            # Only the first item of a group names the type; the rest inherit it
            # along with its packed dimensions.
            if inherited is None:
                inherited = prefix
            elif not prefix.strip():
                prefix = inherited
            base, unknown = _base_width(prefix)
            if base is None:
                ports.append(
                    (
                        name,
                        None,
                        f"data type {unknown!r} has no width this checker can resolve",
                    )
                )
                continue
            width = base
            unresolved: str | None = None
            for bounds in _ONE_RANGE_RE.findall(prefix) + _ONE_RANGE_RE.findall(unpacked):
                if not bounds.strip():
                    continue
                factor = _dimension_factor(bounds, params)
                if factor is None:
                    unresolved = bounds.strip()
                    break
                width *= factor
            if unresolved is not None:
                ports.append((name, None, f"dimension [{unresolved}] is not constant"))
            else:
                ports.append((name, width, ""))
    return ports


def check_asic_top(
    result: Result,
    text: str | None = None,
    info_roles: dict[int, str] | None = None,
    doc_roles: dict[int, str] | None = None,
) -> None:
    text = _strip_comments(ASIC_TOP.read_text() if text is None else text)

    for port in ("ui_in", "uo_out", "uio_in", "uio_out", "uio_oe"):
        if not re.search(rf"\[\s*{PIN_WIDTH - 1}\s*:\s*0\s*\]\s*{port}\b", text):
            result.errors.append(
                f"{ASIC_TOP.name}: port {port} is not declared "
                f"[{PIN_WIDTH - 1}:0]; the pin interface must stay {PIN_WIDTH} bits"
            )

    oe = _declared_oe(text)
    if oe is None:
        result.errors.append(f"{ASIC_TOP.name}: could not read a uio_oe direction mask")
        return
    if oe != EXPECTED_UIO_OE:
        result.errors.append(
            f"{ASIC_TOP.name}: uio_oe is {oe:#010b}, "
            f"contract requires {EXPECTED_UIO_OE:#010b}"
        )
    result.facts.append(f"uio_oe direction mask {oe:#010b} (bit set = ASIC drives)")

    info_roles = _uio_roles_from_info() if info_roles is None else info_roles
    doc_roles = _uio_roles_from_protocol() if doc_roles is None else doc_roles
    for index in range(PIN_WIDTH):
        in_info = info_roles.get(index)
        in_doc = doc_roles.get(index)
        if in_info is None:
            result.errors.append(f"info.yaml: uio[{index}] has no documented role")
            continue
        if in_doc is None:
            result.observations.append(
                f"{PROTOCOL_DOC.name}: uio[{index}] role not parsed from prose"
            )
        elif in_doc == in_info:
            continue
        elif _is_abbreviation(in_doc, in_info):
            result.observations.append(
                f"uio[{index}] role spelled {in_doc} in {PROTOCOL_DOC.name} and "
                f"{in_info} in info.yaml; same pin, unaligned wording for the "
                "owning lanes to reconcile"
            )
        else:
            result.errors.append(
                f"uio[{index}] role drift: info.yaml={in_info}, "
                f"{PROTOCOL_DOC.name}={in_doc}"
            )

    terms = _uio_out_terms(text)
    if terms is None:
        result.errors.append(
            f"{ASIC_TOP.name}: could not read an {PIN_WIDTH}-term uio_out concatenation"
        )
        return

    for index in range(PIN_WIDTH):
        term = terms[PIN_WIDTH - 1 - index]
        drives = bool(oe & (1 << index))
        role = info_roles.get(index, f"uio[{index}]")
        if not drives:
            if not _is_literal_zero(term):
                result.errors.append(
                    f"uio[{index}] ({role}) is an input per uio_oe but uio_out "
                    f"drives {term!r}; the ASIC must not back-drive an input pin"
                )
            continue
        if _is_literal_zero(term):
            result.errors.append(
                f"uio[{index}] ({role}) is an output per uio_oe but uio_out ties "
                "it to zero; the documented status bit would never be observable"
            )
            continue
        hint = DRIVEN_ROLE_HINTS.get(role)
        if hint is not None and hint not in term.lower():
            result.observations.append(
                f"uio[{index}] ({role}) is driven by {term!r}, which does not "
                f"contain {hint!r}; confirm the mapping is still intended"
            )

    result.facts.append(
        "uio_out drives exactly the bits uio_oe marks as outputs, "
        "and ties every input bit to zero"
    )


def check_harness_width(
    result: Result, sources: dict[str, str] | None = None
) -> None:
    """No harness RTL port may be wider than the pin interface.

    Deliberately conservative: the checker cannot tell an ASIC-facing port from
    a host-side one, so it rejects every wide port. Wide host-side buffering is
    still available through internal signals, which are not ports.
    """
    if sources is None:
        # Recursive and both Verilog suffixes: a nested directory or a .v file
        # would otherwise carry a wide bypass straight past this gate.
        sources = {
            str(path.relative_to(HARNESS_RTL_DIR)): path.read_text()
            for path in sorted(HARNESS_RTL_DIR.rglob("*"))
            if path.is_file() and path.suffix in RTL_SUFFIXES
        }
    if not sources:
        result.errors.append(f"{HARNESS_RTL_DIR}: no harness RTL found")
        return
    for name, text in sources.items():
        flagged = False
        for port, width, detail in _port_widths(_strip_comments(text)):
            if width is None:
                flagged = True
                result.errors.append(
                    f"{name}: port {port} cannot be sized because {detail}; an "
                    "unverifiable width is treated as a potential wide bypass. "
                    "Declare the port with a built-in type and literal or "
                    "locally-resolvable bounds"
                )
            elif width > PIN_WIDTH:
                flagged = True
                result.errors.append(
                    f"{name}: port {port} is {width} bits wide; a port wider "
                    f"than {PIN_WIDTH} bits across the ASIC boundary is a wide "
                    "bypass and is prohibited"
                )
        if not flagged:
            result.facts.append(
                f"{name}: every port width resolved and within {PIN_WIDTH} bits"
            )


def run() -> Result:
    result = Result(errors=[], observations=[], facts=[])
    check_asic_top(result)
    check_harness_width(result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--quiet", action="store_true", help="print only failures and the verdict"
    )
    args = parser.parse_args(argv)

    result = run()
    if not args.quiet:
        for fact in result.facts:
            print(f"  ok  {fact}")
    for note in result.observations:
        print(f"  note {note}")
    for error in result.errors:
        print(f"  FAIL {error}", file=sys.stderr)

    if result.ok:
        print("LSC-1 pin-accurate harness boundary: OK")
        return 0
    print(
        f"LSC-1 pin-accurate harness boundary: {len(result.errors)} violation(s)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

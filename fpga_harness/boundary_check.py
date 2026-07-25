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


def check_asic_top(
    result: Result,
    text: str | None = None,
    info_roles: dict[int, str] | None = None,
    doc_roles: dict[int, str] | None = None,
) -> None:
    text = ASIC_TOP.read_text() if text is None else text

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
    """No ASIC-facing harness port may be wider than the pin interface."""
    if sources is None:
        sources = {
            path.name: path.read_text()
            for path in sorted(HARNESS_RTL_DIR.glob("*.sv"))
        }
    if not sources:
        result.errors.append(f"{HARNESS_RTL_DIR}: no harness RTL found")
        return
    for name, text in sources.items():
        for match in re.finditer(
            r"\b(?:input|output|inout)\b[^;,()]*?\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*(\w+)",
            text,
        ):
            high, low = int(match.group(1)), int(match.group(2))
            port = match.group(3)
            width = abs(high - low) + 1
            if width > PIN_WIDTH:
                result.errors.append(
                    f"{name}: port {port} is {width} bits wide; a port wider "
                    f"than {PIN_WIDTH} bits across the ASIC boundary is a wide "
                    "bypass and is prohibited"
                )
        result.facts.append(f"{name}: all ASIC-facing ports within {PIN_WIDTH} bits")


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

#!/usr/bin/env python3
"""Elaborated semantic oracle for the production BLAKE pending implication."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

CONTRACT_VERSION = 4
TOP = "full_lsc1_controller_invariants"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bit(value: object, values: dict[int, int]) -> int:
    if value == "0": return 0
    if value == "1": return 1
    if isinstance(value, int) and value in values: return values[value]
    raise KeyError(value)


def _evaluate(module: dict, outputs: list[object], inputs: dict[int, int]) -> list[int]:
    values = dict(inputs)
    pending = dict(module.get("cells", {}))
    while pending:
        progress = False
        for name, cell in list(pending.items()):
            if cell["type"] == "$assert" or "Y" not in cell.get("connections", {}):
                del pending[name]
                progress = True
                continue
            con = cell["connections"]
            try:
                if cell["type"] == "$mux":
                    result = [_bit(b if _bit(con["S"][0], values) else a, values)
                              for a, b in zip(con["A"], con["B"])]
                elif cell["type"] in ("$not", "$logic_not"):
                    result = [int(not _bit(con["A"][0], values))]
                elif cell["type"] in ("$and", "$logic_and"):
                    result = [_bit(con["A"][0], values) & _bit(con["B"][0], values)]
                elif cell["type"] in ("$or", "$logic_or"):
                    result = [_bit(con["A"][0], values) | _bit(con["B"][0], values)]
                else:
                    continue
            except KeyError:
                continue
            for bit, value in zip(con["Y"], result):
                if isinstance(bit, int): values[bit] = value
            del pending[name]
            progress = True
        if not progress: break
    return [_bit(bit, values) for bit in outputs]


def _formal_kind(cell: dict) -> tuple[str | None, str]:
    """Normalize formal cells emitted by supported Yosys generations."""
    cell_type = cell.get("type")
    if cell_type in ("$assert", "$assume", "$cover"):
        return cell_type[1:], "legacy_formal_cell"
    if cell_type == "$check":
        flavor = cell.get("parameters", {}).get("FLAVOR")
        if flavor in ("assert", "assume", "cover", "live", "fair"):
            return flavor, "check_flavor_cell"
        return None, "unknown_check_flavor"
    return None, "not_formal"


def _parameter_uint(value: object) -> int:
    """Decode the binary parameter strings used by Yosys JSON, fail closed."""
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value and set(value) <= {"0", "1"}:
        return int(value, 2)
    raise ValueError(value)


def _trigger_kind(cell: dict, representation: str) -> str:
    """Classify whether a supported formal cell is live continuously or on an event."""
    if representation == "legacy_formal_cell":
        # Legacy $assert/$assume/$cover cells have no trigger ports: their A/EN
        # inputs are the continuously evaluated formal semantics.
        return "legacy_combinational"
    if representation != "check_flavor_cell":
        return "not_applicable"

    parameters = cell.get("parameters", {})
    connections = cell.get("connections", {})
    required = {"TRG_ENABLE", "TRG_WIDTH", "TRG_POLARITY"}
    if not required.issubset(parameters) or "TRG" not in connections:
        return "unknown_check_trigger"
    try:
        enabled = _parameter_uint(parameters["TRG_ENABLE"])
        width = _parameter_uint(parameters["TRG_WIDTH"])
    except ValueError:
        return "unknown_check_trigger"
    polarity = parameters["TRG_POLARITY"]
    trigger = connections["TRG"]
    if not isinstance(polarity, str) or not isinstance(trigger, list):
        return "unknown_check_trigger"
    if enabled == 0 and width == 0 and polarity == "" and trigger == []:
        return "check_combinational"
    if enabled != 1 or width <= 0 or len(polarity) != width or len(trigger) != width:
        return "unknown_check_trigger"
    if set(polarity) - {"0", "1"}:
        return "unknown_check_trigger"
    if width == 1:
        return "check_posedge_triggered" if polarity == "1" else "check_negedge_triggered"
    return "check_event_triggered"


def validate_design(design: dict) -> tuple[bool, str, dict]:
    """Validate an already elaborated design (also used by version fixtures)."""
    module = design.get("modules", {}).get(TOP)
    if not module:
        return False, "production_invariant_top_missing", {}
    ports = module.get("ports", {})
    try:
        result_bit = ports["result_pending"]["bits"][0]
        blake_bit = ports["blake_result_pending"]["bits"][0]
    except (KeyError, IndexError):
        return False, "production_pending_ports_missing", {}
    matches = []
    representations: dict[str, int] = {}
    triggers: dict[str, int] = {}
    unknown = []
    for name, cell in module.get("cells", {}).items():
        kind, representation = _formal_kind(cell)
        if representation != "not_formal":
            representations[representation] = representations.get(representation, 0) + 1
        if representation == "unknown_check_flavor":
            unknown.append(name)
            continue
        if kind != "assert":
            continue
        trigger = _trigger_kind(cell, representation)
        triggers[trigger] = triggers.get(trigger, 0) + 1
        if trigger == "unknown_check_trigger":
            unknown.append(name)
            continue
        if trigger not in ("legacy_combinational", "check_combinational"):
            continue
        con = cell.get("connections", {})
        if not {"A", "EN"}.issubset(con) or len(con["A"]) != 1 or len(con["EN"]) != 1:
            unknown.append(name)
            continue
        truth = []
        try:
            for result in (0, 1):
                for blake in (0, 1):
                    assignment = {result_bit: result, blake_bit: blake}
                    en = _evaluate(module, [con["EN"][0]], assignment)[0]
                    a = _evaluate(module, [con["A"][0]], assignment)[0] if en else 1
                    truth.append((result, blake, a, en))
        except KeyError:
            continue
        violations = {(r, b) for r, b, a, en in truth if en and not a}
        if violations == {(0, 1)}:
            matches.append(name)
    meta = {"top": TOP, "representation_classification": representations,
            "trigger_classification": triggers,
            "unknown_formal_cells": unknown, "live_assert_cells": len(matches),
            "matching_cells": matches}
    if unknown:
        return False, "unsupported_formal_cell_representation", meta
    if len(matches) != 1:
        return False, f"production_blake_pending_implication_cells={len(matches)};expected=1", meta
    return True, "production_blake_pending_implication_elaborated", meta


def validate(path: Path) -> tuple[bool, str, dict]:
    with tempfile.TemporaryDirectory(prefix="blake-pending-contract-") as raw:
        netlist = Path(raw) / "invariant.json"
        command = ["yosys", "-q", "-p",
                   f"read_verilog -formal -sv {path}; hierarchy -check -top {TOP}; proc; opt_expr; opt_clean; write_json {netlist}"]
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        meta = {"command": command, "source_sha256": sha256(path)}
        if completed.returncode:
            return False, "production_invariant_elaboration_failed", {**meta, "output": completed.stdout[-2000:]}
        design = json.loads(netlist.read_text())
    valid, reason, design_meta = validate_design(design)
    return valid, reason, {**meta, **design_meta}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_blake3_pending_contract.py INVARIANT", file=sys.stderr)
        return 2
    path = Path(argv[1]).resolve()
    valid, reason, meta = validate(path)
    version = subprocess.run(["yosys", "-V"], text=True, stdout=subprocess.PIPE).stdout.strip()
    print(json.dumps({"contract_version": CONTRACT_VERSION, "valid": valid, "reason": reason,
                      "validator_sha256": sha256(Path(__file__)), "yosys_version": version, **meta},
                     sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

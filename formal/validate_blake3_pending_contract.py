#!/usr/bin/env python3
"""Elaborated semantic oracle for the production BLAKE pending implication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

CONTRACT_VERSION = 7
TOP = "full_lsc1_controller_invariants"
ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / ".github" / "toolchains" / "oss-cad-suite-20260809.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text())
MANIFEST_SHA256 = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
SUPPORTED_YOSYS_REPRESENTATION = "$check with FLAVOR=assert and explicit TRG metadata"
SUPPORTED_YOSYS_RANGE = "repository-pinned OSS CAD Suite Yosys 0.68+40"
SUPPORTED_YOSYS_VERSION = MANIFEST["yosys_version"]
SUPPORTED_YOSYS_GIT_SHA = MANIFEST["yosys_git_sha"]


def _fd_digest(fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, 1024 * 1024):
        digest.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return digest.hexdigest()


def _identity(st: os.stat_result) -> dict:
    return {"device": st.st_dev, "inode": st.st_ino, "mode": st.st_mode,
            "size": st.st_size, "mtime_ns": st.st_mtime_ns, "ctime_ns": st.st_ctime_ns}


def _open_stable(path: Path, expected_digest: str | None = None) -> tuple[int, dict]:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise RuntimeError(f"no_follow_open_failed:{error.errno}") from error
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        os.close(fd)
        raise RuntimeError("not_regular_file")
    digest = _fd_digest(fd)
    if expected_digest is not None and digest != expected_digest:
        os.close(fd)
        raise RuntimeError("digest_mismatch")
    return fd, {**_identity(st), "sha256": digest}


def _verify_unchanged(fd: int, path: Path, before: dict) -> tuple[bool, dict]:
    try:
        fd_stat = os.fstat(fd)
        path_stat = os.stat(path, follow_symlinks=False)
        after = {**_identity(fd_stat), "sha256": _fd_digest(fd)}
        path_identity = _identity(path_stat)
        expected_identity = {key: before[key] for key in path_identity}
        stable = after == before and path_identity == expected_identity
        return stable, after
    except OSError:
        return False, {"error": "post_execution_stat_failed"}


def _yosys_identity(value: object) -> tuple[str, str] | None:
    """Extract the pinned version/build identity from genuine Yosys banners."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"Yosys ([0-9]+\.[0-9]+\+[0-9]+) \(git sha1 ([0-9a-f]{9})(?:-dirty)?(?:,.*)?\)",
        value.strip(),
    )
    if not match:
        return None
    return match.group(1), match.group(2)


def _provenance(design: dict, runtime_version: object) -> tuple[bool, str, dict]:
    creator = design.get("creator")
    creator_identity = _yosys_identity(creator)
    runtime_identity = _yosys_identity(runtime_version)
    meta = {
        "json_creator": creator,
        "runtime_yosys_version": runtime_version,
        "creator_identity": creator_identity,
        "runtime_identity": runtime_identity,
    }
    expected = (SUPPORTED_YOSYS_VERSION, SUPPORTED_YOSYS_GIT_SHA)
    if creator_identity is None:
        return False, "json_creator_missing_or_malformed", meta
    if runtime_identity is None:
        return False, "runtime_yosys_version_missing_or_malformed", meta
    if creator_identity != expected:
        return False, "json_creator_unsupported_yosys_build", meta
    if runtime_identity != expected:
        return False, "runtime_unsupported_yosys_build", meta
    if creator_identity != runtime_identity:
        return False, "json_creator_runtime_mismatch", meta
    return True, "pinned_yosys_provenance_verified", meta


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
        # The legacy JSON form has no trigger metadata.  Source constructs with
        # materially different sampling semantics can therefore normalize to
        # the same cell interface.  Do not infer continuous evaluation.
        return "legacy_trigger_semantics_insufficient"
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


def validate_design(design: dict, runtime_version: str) -> tuple[bool, str, dict]:
    """Validate an already elaborated design (also used by version fixtures)."""
    provenance_valid, provenance_reason, provenance_meta = _provenance(
        design, runtime_version)
    if not provenance_valid:
        return False, provenance_reason, provenance_meta
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
        if trigger in ("unknown_check_trigger", "legacy_trigger_semantics_insufficient"):
            unknown.append(name)
            continue
        if trigger != "check_combinational":
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
    meta = {**provenance_meta, "provenance": provenance_reason, "top": TOP,
            "supported_yosys_range": SUPPORTED_YOSYS_RANGE,
            "supported_representation": SUPPORTED_YOSYS_REPRESENTATION,
            "representation_classification": representations,
            "trigger_classification": triggers,
            "unknown_formal_cells": unknown, "live_assert_cells": len(matches),
            "matching_cells": matches}
    if unknown:
        return False, "unsupported_formal_cell_representation", meta
    if len(matches) != 1:
        return False, f"production_blake_pending_implication_cells={len(matches)};expected=1", meta
    return True, "production_blake_pending_implication_elaborated", meta


def validate(path: Path, yosys_command: str = "yosys") -> tuple[bool, str, dict]:
    executable = shutil.which(yosys_command)
    if executable is None:
        return False, "yosys_executable_missing", {"yosys_command": yosys_command}
    executable_path = Path(executable).absolute()
    base_meta = {"toolchain_manifest": str(MANIFEST_PATH),
                 "toolchain_manifest_sha256": MANIFEST_SHA256,
                 "expected_yosys_sha256": MANIFEST["yosys_sha256"]}
    try:
        executable_fd, executable_before = _open_stable(
            executable_path, MANIFEST["yosys_sha256"])
    except RuntimeError as error:
        return False, f"yosys_executable_{error}", {**base_meta, "yosys_executable": str(executable_path)}
    try:
        source_fd, source_before = _open_stable(path)
    except RuntimeError as error:
        os.close(executable_fd)
        return False, f"source_{error}", {**base_meta, "source": str(path)}
    version_command = [str(executable_path), "-V"]
    version_result = subprocess.run(version_command, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
    executable_stable, executable_after_version = _verify_unchanged(
        executable_fd, executable_path, executable_before)
    runtime_version = version_result.stdout.strip()
    runtime_meta = {
        **base_meta,
        "yosys_executable": str(executable_path),
        "yosys_executable_observed_before": executable_before,
        "yosys_executable_observed_after_version": executable_after_version,
        "yosys_version_command": version_command,
        "runtime_yosys_version": runtime_version,
    }
    if not executable_stable:
        os.close(source_fd); os.close(executable_fd)
        return False, "yosys_executable_changed_during_version", runtime_meta
    runtime_identity = _yosys_identity(runtime_version)
    if version_result.returncode or runtime_identity != (SUPPORTED_YOSYS_VERSION,
                                                          SUPPORTED_YOSYS_GIT_SHA):
        os.close(source_fd); os.close(executable_fd)
        return False, "runtime_unsupported_yosys_build", runtime_meta
    with tempfile.TemporaryDirectory(prefix="blake-pending-contract-") as raw:
        netlist = Path(raw) / "invariant.json"
        command = [str(executable_path), "-q", "-p",
                   f"read_verilog -formal -sv {path}; hierarchy -check -top {TOP}; proc; opt_expr; opt_clean; write_json {netlist}"]
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        executable_stable, executable_after = _verify_unchanged(
            executable_fd, executable_path, executable_before)
        source_stable, source_after = _verify_unchanged(source_fd, path, source_before)
        os.close(source_fd); os.close(executable_fd)
        meta = {**runtime_meta, "command": command, "source_observed_before": source_before,
                "source_observed_after": source_after,
                "yosys_executable_observed_after_elaboration": executable_after}
        if not executable_stable:
            return False, "yosys_executable_changed_during_elaboration", meta
        if not source_stable:
            return False, "source_changed_during_elaboration", meta
        if completed.returncode:
            return False, "production_invariant_elaboration_failed", {**meta, "output": completed.stdout[-2000:]}
        netlist_bytes = netlist.read_bytes()
        design = json.loads(netlist_bytes)
    valid, reason, design_meta = validate_design(design, runtime_version)
    return valid, reason, {**meta, "json_sha256": hashlib.sha256(netlist_bytes).hexdigest(),
                           **design_meta}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_blake3_pending_contract.py INVARIANT", file=sys.stderr)
        return 2
    path = Path(argv[1]).resolve()
    valid, reason, meta = validate(path)
    print(json.dumps({"contract_version": CONTRACT_VERSION, "valid": valid, "reason": reason,
                      "validator_sha256": sha256(Path(__file__)), **meta},
                     sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

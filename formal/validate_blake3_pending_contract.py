#!/usr/bin/env python3
"""Elaborated semantic oracle for the production BLAKE pending implication."""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path

CONTRACT_VERSION = 14
TOP = "full_lsc1_controller_invariants"
ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / ".github" / "toolchains" / "oss-cad-suite-20260809.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text())
MANIFEST_SHA256 = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
SUPPORTED_YOSYS_REPRESENTATION = "$check with FLAVOR=assert and explicit TRG metadata"
SUPPORTED_YOSYS_RANGE = "repository-pinned OSS CAD Suite Yosys 0.68+40"
SUPPORTED_YOSYS_VERSION = MANIFEST["yosys_version"]
SUPPORTED_YOSYS_GIT_SHA = MANIFEST["yosys_git_sha"]
THREAT_BOUNDARY = {
    "assumption": "trusted isolated CI process and runner after SHA-pinned archive authentication",
    "protects_against": [
        "accidental_or_ambient_PATH_selection",
        "final_component_symlinks",
        "hostile_TMPDIR",
        "stale_or_substituted_extracted_tree_before_validation",
        "output_pathname_replacement",
    ],
    "not_claimed": [
        "same_uid_or_root_concurrent_tampering",
        "ptrace_or_proc_fd_writes",
        "privileged_mount_replacement",
        "kernel_compromise",
    ],
}


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


def _verify_fd_unchanged(fd: int, before: dict) -> tuple[bool, dict]:
    try:
        fd_stat = os.fstat(fd)
        after = {**_identity(fd_stat), "sha256": _fd_digest(fd)}
        return after == before, after
    except OSError:
        return False, {"error": "post_execution_stat_failed"}


def _fd_path(fd: int) -> str:
    """Return a descriptor-backed path, or fail rather than reopen a pathname."""
    path = f"/proc/self/fd/{fd}"
    try:
        st = os.stat(path)
        fd_st = os.fstat(fd)
    except OSError as error:
        raise RuntimeError(f"descriptor_route_unavailable:{error.errno}") from error
    if (st.st_dev, st.st_ino) != (fd_st.st_dev, fd_st.st_ino):
        raise RuntimeError("descriptor_route_identity_mismatch")
    return path


def _sanitized_environment(snapshot: Path) -> tuple[dict[str, str], dict]:
    removed = sorted(k for k in os.environ
                     if k.startswith(("LD_", "YOSYS_")) or k == "TMPDIR")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("LD_", "YOSYS_")) and k != "TMPDIR"}
    env.update({"PATH": str(snapshot / "bin") + ":/usr/bin:/bin",
                "HOME": str(snapshot), "LC_ALL": "C"})
    return env, {"removed_variables": removed,
                 "set_variables": {"PATH": "<snapshot>/bin:/usr/bin:/bin",
                                   "HOME": "<snapshot>", "LC_ALL": "C"}}


def _private_workspace(cleanup: "_CleanupTransaction") -> tuple[Path, int, int, dict]:
    """Create beneath the fixed, no-follow verified system temp parent."""
    parent = Path("/tmp")
    parent_fd = cleanup.open_fd(
        "parent", parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC |
        getattr(os, "O_NOFOLLOW", 0))
    parent_st = _workspace_fstat("parent", parent_fd)
    if not stat.S_ISDIR(parent_st.st_mode) or parent_st.st_uid != 0 or \
            not (parent_st.st_mode & stat.S_ISVTX):
        raise RuntimeError("trusted_temp_parent_policy_failed")
    raw = cleanup.create_private_tree(prefix="blake-pending-contract-", dir="/tmp")
    _workspace_chmod(raw, 0o700)
    workspace_fd = cleanup.open_fd(
        "workspace", raw, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC |
        getattr(os, "O_NOFOLLOW", 0))
    st = _workspace_fstat("workspace", workspace_fd)
    if not _workspace_policy_valid(st):
        raise RuntimeError("private_workspace_policy_failed")
    return raw, parent_fd, workspace_fd, {"device": parent_st.st_dev,
        "inode": parent_st.st_ino, "workspace_device": st.st_dev,
        "workspace_inode": st.st_ino, "owner": st.st_uid, "mode": "0700"}


def _workspace_fstat(name: str, fd: int) -> os.stat_result:
    """Named acquisition seam used by production-path fault regressions."""
    del name
    return os.fstat(fd)


def _workspace_chmod(path: Path, mode: int) -> None:
    """Named acquisition seam used by production-path fault regressions."""
    os.chmod(path, mode)


def _workspace_policy_valid(st: os.stat_result) -> bool:
    """Keep owner/mode verification independently fault-testable."""
    return st.st_uid == os.getuid() and stat.S_IMODE(st.st_mode) == 0o700


def _tree_identity(root: Path) -> dict:
    """Hash the extracted namespace and reject aliases/special objects."""
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*"), key=lambda p: os.fsencode(p.relative_to(root))):
        relative = os.fsencode(path.relative_to(root))
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode):
            raise RuntimeError("snapshot_symlink_not_sealed")
        if not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
            raise RuntimeError("snapshot_special_file")
        if stat.S_ISREG(st.st_mode) and st.st_nlink != 1:
            raise RuntimeError("snapshot_hardlink_not_sealed")
        digest.update(relative + b"\0" + str(st.st_mode & ~0o222).encode() + b"\0" +
                      str(st.st_size).encode() + b"\0")
        if stat.S_ISREG(st.st_mode):
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024): digest.update(chunk)
            os.chmod(path, stat.S_IMODE(st.st_mode) & ~0o222)
        count += 1
    for path in sorted((p for p in root.rglob("*") if p.is_dir()),
                       key=lambda p: len(p.parts), reverse=True):
        os.chmod(path, stat.S_IMODE(path.stat().st_mode) & ~0o222)
    os.chmod(root, stat.S_IMODE(root.stat().st_mode) & ~0o222)
    return {"sha256": digest.hexdigest(), "entries": count}


def _read_output_fd(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    while chunk := os.read(fd, 1024 * 1024): chunks.append(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return b"".join(chunks)


def _remove_private_tree(path: Path) -> None:
    """Restore sealed-tree permissions bottom-up, remove it, and verify residue."""
    if not path.exists():
        return
    failures: list[str] = []
    entries = sorted(path.rglob("*"), key=lambda entry: len(entry.parts), reverse=True)
    for entry in entries:
        try:
            if not entry.is_symlink():
                os.chmod(entry, 0o700 if entry.is_dir() else 0o600)
        except OSError as error:
            failures.append(f"chmod:{entry.relative_to(path)}:{error.errno}")
    try:
        os.chmod(path, 0o700)
    except OSError as error:
        failures.append(f"chmod:.:{error.errno}")
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        try:
            residue = [str(entry.relative_to(path)) for entry in path.rglob("*")][:20]
        except OSError as error:
            residue = [f"unreadable:{error.errno}"]
        detail = ",".join(failures + residue) or "unknown"
        raise RuntimeError(f"private_workspace_cleanup_incomplete:{detail}")


class _CleanupFailures(RuntimeError):
    """Deterministic aggregate of cleanup actions; every action was attempted."""

    def __init__(self, failures: list[dict]) -> None:
        self.failures = failures
        super().__init__(json.dumps(failures, sort_keys=True, separators=(",", ":")))


class _CleanupTransaction:
    """Own descriptors and the private tree until one ordered cleanup pass."""

    _FD_ORDER = ("output", "source", "archive", "loader", "yosys", "boundary",
                 "workspace", "parent")

    def __init__(self) -> None:
        self._fds: dict[str, int] = {}
        self.private: Path | None = None

    def _register_fd(self, name: str, fd: int) -> None:
        """Registration seam: callers retain rollback ownership until this returns."""
        self._fds[name] = fd

    def _register_private_tree(self, path: Path) -> None:
        """Registration seam: callers retain rollback ownership until this returns."""
        self.private = path

    def own_fd(self, name: str, fd: int) -> int:
        if name in self._fds:
            raise RuntimeError(f"cleanup_fd_ownership_duplicate:{name}")
        try:
            self._register_fd(name, fd)
        except BaseException as registration_error:
            try:
                _close_owned_fd(name, fd)
            except BaseException as rollback_error:
                _attach_secondary_cleanup_failure(
                    registration_error, f"rollback_close_{name}", rollback_error)
            raise
        return fd

    def open_fd(self, name: str, path: os.PathLike[str] | str, flags: int,
                mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        """Open and register without exposing an unowned descriptor to the caller."""
        if name in self._fds:
            raise RuntimeError(f"cleanup_fd_ownership_duplicate:{name}")
        fd = os.open(path, flags, mode, dir_fd=dir_fd)
        try:
            self._register_fd(name, fd)
        except BaseException as registration_error:
            try:
                _close_owned_fd(name, fd)
            except BaseException as rollback_error:
                _attach_secondary_cleanup_failure(
                    registration_error, f"rollback_close_{name}", rollback_error)
            raise
        return fd

    def create_private_tree(self, *, prefix: str, dir: str) -> Path:
        """Create and register without exposing an unowned tree to the caller."""
        if self.private is not None:
            raise RuntimeError("cleanup_private_tree_ownership_duplicate")
        path = Path(tempfile.mkdtemp(prefix=prefix, dir=dir))
        try:
            self._register_private_tree(path)
        except BaseException as registration_error:
            try:
                _remove_private_tree(path)
            except BaseException as rollback_error:
                _attach_secondary_cleanup_failure(
                    registration_error, "rollback_remove_private_tree", rollback_error)
            raise
        return path

    def own_private_tree(self, path: Path) -> None:
        if self.private is not None:
            raise RuntimeError("cleanup_private_tree_ownership_duplicate")
        try:
            self._register_private_tree(path)
        except BaseException as registration_error:
            try:
                _remove_private_tree(path)
            except BaseException as rollback_error:
                _attach_secondary_cleanup_failure(
                    registration_error, "rollback_remove_private_tree", rollback_error)
            raise

    def run(self) -> None:
        failures: list[dict] = []
        for name in self._FD_ORDER:
            if name not in self._fds:
                continue
            fd = self._fds.pop(name)
            try:
                _close_owned_fd(name, fd)
            except BaseException as error:
                failures.append({"action": f"close_{name}",
                                 "type": type(error).__name__, "message": str(error)})
        if self.private is not None:
            private, self.private = self.private, None
            try:
                _remove_private_tree(private)
            except BaseException as error:
                failures.append({"action": "remove_private_tree",
                                 "type": type(error).__name__, "message": str(error)})
        if failures:
            raise _CleanupFailures(failures)


def _close_owned_fd(name: str, fd: int) -> None:
    """Named seam for production-path cleanup fault-injection regressions."""
    del name
    os.close(fd)


def _attach_secondary_cleanup_failure(
        primary_error: BaseException, action: str, cleanup_error: BaseException) -> None:
    """Attach a registration rollback failure without replacing its primary error."""
    failure = {"action": action, "type": type(cleanup_error).__name__,
               "message": str(cleanup_error)}
    secondary = {"classification": "secondary",
                 "type": "_CleanupFailures",
                 "message": json.dumps([failure], sort_keys=True, separators=(",", ":")),
                 "failures": [failure]}
    primary_error.add_note(
        f"secondary cleanup failure: {type(cleanup_error).__name__}: {cleanup_error}")
    setattr(primary_error, "cleanup_failure", secondary)


def _with_attached_cleanup_failure(meta: dict, error: BaseException) -> dict:
    """Copy rollback classification from an acquisition exception into its receipt."""
    if not hasattr(error, "cleanup_failure"):
        return meta
    return {**meta, "cleanup_failure": error.cleanup_failure}


def _preserve_primary_across_cleanup(
        primary_outcome: list | tuple | None,
        primary_error: BaseException | None,
        cleanup: Callable[[], None]) -> dict | None:
    """Run cleanup without allowing it to mask a primary result or exception."""
    try:
        cleanup()
    except BaseException as cleanup_error:
        secondary = {
            "classification": "secondary" if primary_error is not None or (
                primary_outcome is not None and not primary_outcome[0]) else "principal",
            "type": type(cleanup_error).__name__,
            "message": str(cleanup_error),
        }
        if isinstance(cleanup_error, _CleanupFailures):
            secondary["failures"] = cleanup_error.failures
        if primary_error is not None:
            primary_error.add_note(
                f"secondary cleanup failure: {type(cleanup_error).__name__}: {cleanup_error}")
            setattr(primary_error, "cleanup_failure", secondary)
            return secondary
        if primary_outcome is not None and not primary_outcome[0]:
            primary_outcome[2]["cleanup_failure"] = secondary
            return secondary
        if isinstance(primary_outcome, list):
            primary_outcome[:] = [False, "private_workspace_cleanup_failed", {
                "cleanup_failure": secondary}]
        return secondary
    return None


def _run_authenticated(executable: str, arguments: list[str], inherited_fds: tuple[int, ...],
                       env: dict[str, str] | None = None
                       ) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [executable, *arguments], executable=executable, pass_fds=inherited_fds,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
    )


def _extract_authenticated_archive(archive_fd: int, private: Path) -> Path:
    """Privately materialize the archive root; never consume an extracted original."""
    os.lseek(archive_fd, 0, os.SEEK_SET)
    with os.fdopen(os.dup(archive_fd), "rb") as stream, tarfile.open(fileobj=stream,
                                                                     mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            parts = Path(member.name).parts
            if not parts or parts[0] != "oss-cad-suite" or ".." in parts:
                raise RuntimeError("archive_member_outside_suite")
            if member.isdev() or member.isfifo():
                raise RuntimeError("archive_special_member")
            if member.issym() or member.islnk():
                if member.linkname.startswith("/"):
                    raise RuntimeError("archive_link_not_confined")
                effective = posixpath.normpath(posixpath.join(
                    posixpath.dirname(member.name), member.linkname))
                if effective != "oss-cad-suite" and not effective.startswith("oss-cad-suite/"):
                    raise RuntimeError("archive_link_not_confined")
        archive.extractall(private, members=members, filter="fully_trusted")
    os.lseek(archive_fd, 0, os.SEEK_SET)
    snapshot = private / "oss-cad-suite"
    if not snapshot.is_dir():
        raise RuntimeError("archive_suite_root_missing")
    for path in sorted(snapshot.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_symlink():
            target = path.resolve(strict=True)
            try:
                target.relative_to(snapshot.resolve())
            except ValueError as error:
                raise RuntimeError("archive_link_not_confined") from error
            path.unlink()
            if target.is_dir():
                shutil.copytree(target, path, symlinks=False)
            else:
                shutil.copy2(target, path)
        elif path.is_file() and path.stat().st_nlink > 1:
            replacement = path.with_name(path.name + ".sealed-copy")
            shutil.copy2(path, replacement)
            os.replace(replacement, path)
    return snapshot


def _snapshot_yosys_command(snapshot: Path) -> tuple[str, list[str]]:
    loader = snapshot / "lib" / "ld-linux-x86-64.so.2"
    yosys = snapshot / "libexec" / "yosys"
    if not loader.is_file() or not yosys.is_file():
        raise RuntimeError("snapshot_runtime_entry_missing")
    return str(loader), ["--inhibit-cache", "--inhibit-rpath", "",
                         "--library-path", str(snapshot / "lib"), str(yosys)]


def _audit_snapshot_dependencies(executable: str, prefix: list[str], snapshot: Path,
                                 env: dict[str, str], archive_fd: int) -> tuple[bool, str]:
    result = _run_authenticated(executable, [*prefix[:-1], "--list", prefix[-1]],
                                (archive_fd,), env)
    if result.returncode:
        return False, result.stdout
    root = str(snapshot) + os.sep
    for line in result.stdout.splitlines():
        match = re.search(r"=>\s+(/\S+)", line)
        if match is None:
            match = re.match(r"\s*(/\S+)", line)
        if match and not match.group(1).startswith(root):
            return False, result.stdout
    return True, result.stdout


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


def _validate_primary(path: Path, yosys_command: str,
                      cleanup: _CleanupTransaction) -> tuple[bool, str, dict]:
    executable = shutil.which(yosys_command)
    if executable is None:
        return False, "yosys_executable_missing", {"yosys_command": yosys_command}
    # Deliberately do not resolve either object: final-component symlinks must
    # reach O_NOFOLLOW, and authenticated objects are consumed only by fd.
    executable_path = Path(os.path.abspath(executable))
    source_path = Path(os.path.abspath(os.fspath(path)))
    archive_value = os.environ.get(MANIFEST["archive_environment_variable"])
    base_meta = {"toolchain_manifest": str(MANIFEST_PATH),
                 "toolchain_manifest_sha256": MANIFEST_SHA256,
                 "archive_sha256": MANIFEST["archive_sha256"],
                 "archive_bytes": MANIFEST["archive_bytes"],
                 "threat_boundary": THREAT_BOUNDARY,
                 "snapshot_route": "fixed-parent_sealed_snapshot_descriptor_entries"}
    # The caller-selected command is authenticated as a boundary check, but is
    # never executed; runtime consumption comes exclusively from the archive.
    try:
        boundary_fd, boundary_meta = _open_stable(executable_path, MANIFEST["yosys_sha256"])
        cleanup.own_fd("boundary", boundary_fd)
    except RuntimeError as error:
        return False, f"yosys_executable_{error}", _with_attached_cleanup_failure(
            base_meta, error)
    base_meta["caller_yosys_observed"] = boundary_meta
    if archive_value is None:
        return False, "authenticated_archive_path_missing", base_meta
    archive_path = Path(os.path.abspath(archive_value))
    try:
        archive_fd, archive_before = _open_stable(archive_path, MANIFEST["archive_sha256"])
        cleanup.own_fd("archive", archive_fd)
    except RuntimeError as error:
        return False, f"archive_{error}", _with_attached_cleanup_failure(base_meta, error)
    if archive_before["size"] != MANIFEST["archive_bytes"]:
        return False, "archive_size_mismatch", {**base_meta,
                                                 "archive_observed_before": archive_before}
    try:
        source_fd, source_before = _open_stable(source_path)
        cleanup.own_fd("source", source_fd)
    except RuntimeError as error:
        return False, f"source_{error}", _with_attached_cleanup_failure(base_meta, error)
    try:
        source_route = _fd_path(source_fd)
    except RuntimeError as error:
        return False, str(error), base_meta
    try:
        private, parent_fd, workspace_fd, workspace_meta = _private_workspace(cleanup)
    except (OSError, RuntimeError) as error:
        return False, f"private_workspace_failed:{error}", \
            _with_attached_cleanup_failure(base_meta, error)

    def outcome(valid: bool, reason: str, details: dict) -> tuple[bool, str, dict]:
        return valid, reason, details

    try:
        try:
            snapshot = _extract_authenticated_archive(archive_fd, private)
        except (OSError, RuntimeError) as error:
            return outcome(False, f"authenticated_archive_extraction_failed:{error}", base_meta)
        snapshot_yosys = snapshot / MANIFEST["yosys_relative_path"]
        if sha256(snapshot_yosys) != MANIFEST["yosys_sha256"]:
            return outcome(False, "snapshot_yosys_digest_mismatch", base_meta)
        runtime_env, env_meta = _sanitized_environment(snapshot)
        try:
            runtime_executable, runtime_prefix = _snapshot_yosys_command(snapshot)
        except RuntimeError as error:
            return outcome(False, str(error), base_meta)
        dependencies_valid, dependency_audit = _audit_snapshot_dependencies(
            runtime_executable, runtime_prefix, snapshot, runtime_env, archive_fd)
        if not dependencies_valid:
            return outcome(False, "snapshot_runtime_dependency_outside_archive", {
                **base_meta, "runtime_dependency_audit": dependency_audit})
        try:
            snapshot_identity = _tree_identity(snapshot)
        except (OSError, RuntimeError) as error:
            return outcome(False, f"snapshot_sealing_failed:{error}", base_meta)
        try:
            loader_fd, loader_before = _open_stable(
                snapshot / "lib" / "ld-linux-x86-64.so.2")
            cleanup.own_fd("loader", loader_fd)
            yosys_fd, yosys_before = _open_stable(snapshot / "libexec" / "yosys")
            cleanup.own_fd("yosys", yosys_fd)
            runtime_executable = _fd_path(loader_fd)
            runtime_prefix = ["--inhibit-cache", "--inhibit-rpath", "",
                              "--library-path", str(snapshot / "lib"),
                              _fd_path(yosys_fd)]
        except (OSError, RuntimeError) as error:
            return outcome(False, f"snapshot_descriptor_route_failed:{error}", base_meta)
        runtime_files = {}
        for relative in (MANIFEST["yosys_relative_path"], "lib/ld-linux-x86-64.so.2",
                         "libexec/yosys"):
            candidate = snapshot / relative
            runtime_files[relative] = {"size": candidate.stat().st_size,
                                       "sha256": sha256(candidate)}
        version_command = ["authenticated-snapshot/lib/ld-linux-x86-64.so.2",
                           "<sealed-loader-options>", "libexec/yosys", "-V"]
        version_result = _run_authenticated(
            runtime_executable, [*runtime_prefix, "-V"],
            (archive_fd, loader_fd, yosys_fd), runtime_env)
        archive_stable, archive_after_version = _verify_fd_unchanged(
            archive_fd, archive_before)
        runtime_version = version_result.stdout.strip()
        runtime_meta = {
            **base_meta,
            "archive_fd": archive_fd,
            "source_fd": source_fd,
            "archive_observed_before": archive_before,
            "archive_observed_after_version": archive_after_version,
            "yosys_version_command": version_command,
            "runtime_yosys_version": runtime_version,
            "sanitized_environment": env_meta,
            "observed_runtime_files": runtime_files,
            "runtime_dependency_audit": dependency_audit,
            "runtime_descriptor_objects": {"loader": loader_before,
                                             "yosys": yosys_before},
        }
        if not archive_stable:
            return outcome(False, "archive_changed_during_version", runtime_meta)
        runtime_identity = _yosys_identity(runtime_version)
        if version_result.returncode or runtime_identity != (SUPPORTED_YOSYS_VERSION,
                                                              SUPPORTED_YOSYS_GIT_SHA):
            return outcome(False, "runtime_unsupported_yosys_build", runtime_meta)
        output_fd = os.open("invariant.json", os.O_RDWR | os.O_CREAT | os.O_EXCL |
                            os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0), 0o600,
                            dir_fd=workspace_fd)
        cleanup.own_fd("output", output_fd)
        output_route = _fd_path(output_fd)
        script = (f"read_verilog -formal -sv {source_route}; "
                  f"hierarchy -check -top {TOP}; proc; opt_expr; opt_clean; "
                  f"write_json {output_route}")
        command = ["authenticated-snapshot/lib/ld-linux-x86-64.so.2",
                   "<sealed-loader-options>", "libexec/yosys", "-q", "-p", script]
        completed = _run_authenticated(
            runtime_executable, [*runtime_prefix, "-q", "-p", script],
            (archive_fd, source_fd, output_fd, loader_fd, yosys_fd), runtime_env)
        archive_stable, archive_after = _verify_fd_unchanged(archive_fd, archive_before)
        source_stable, source_after = _verify_fd_unchanged(source_fd, source_before)
        loader_stable, loader_after = _verify_fd_unchanged(loader_fd, loader_before)
        yosys_stable, yosys_after = _verify_fd_unchanged(yosys_fd, yosys_before)
        try:
            snapshot_after = _tree_identity(snapshot)
        except (OSError, RuntimeError) as error:
            snapshot_after = {"error": str(error)}
        meta = {**runtime_meta, "command": command, "source_observed_before": source_before,
                "source_observed_after": source_after,
        "archive_observed_after_elaboration": archive_after,
        "consumption_route": "fixed_parent_sealed_snapshot_descriptor_runtime_and_io",
        "output_directory_mode": "0700", "trusted_workspace": workspace_meta,
        "snapshot_identity_before": snapshot_identity,
        "snapshot_identity_after": snapshot_after,
        "runtime_descriptor_objects_after": {"loader": loader_after,
                                               "yosys": yosys_after},
        "output_consumption_route": "preopened_inherited_descriptor"}
        if not archive_stable:
            return outcome(False, "archive_changed_during_elaboration", meta)
        if not source_stable:
            return outcome(False, "source_changed_during_elaboration", meta)
        if snapshot_after != snapshot_identity:
            return outcome(False, "snapshot_changed_during_elaboration", meta)
        if not loader_stable or not yosys_stable:
            return outcome(False, "runtime_descriptor_changed_during_elaboration", meta)
        if completed.returncode:
            return outcome(False, "production_invariant_elaboration_failed",
                           {**meta, "output": completed.stdout[-2000:]})
        netlist_bytes = _read_output_fd(output_fd)
        design = json.loads(netlist_bytes)
        valid, reason, design_meta = validate_design(design, runtime_version)
        return outcome(valid, reason, {
            **meta, "json_sha256": hashlib.sha256(netlist_bytes).hexdigest(),
            **design_meta})
    finally:
        pass


def validate(path: Path, yosys_command: str = "yosys") -> tuple[bool, str, dict]:
    """Validate and preserve the primary outcome across the full cleanup transaction."""
    cleanup = _CleanupTransaction()
    primary_outcome: list | None = None
    try:
        primary_outcome = list(_validate_primary(path, yosys_command, cleanup))
        return primary_outcome
    finally:
        _preserve_primary_across_cleanup(primary_outcome, sys.exception(), cleanup.run)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_blake3_pending_contract.py INVARIANT", file=sys.stderr)
        return 2
    path = Path(os.path.abspath(argv[1]))
    valid, reason, meta = validate(path)
    print(json.dumps({"contract_version": CONTRACT_VERSION, "valid": valid, "reason": reason,
                      "validator_sha256": sha256(Path(__file__)), **meta},
                     sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

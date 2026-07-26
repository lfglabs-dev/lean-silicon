#!/usr/bin/env python3
"""Portable locking and SHA-256 manifests for ULX3S build archives.

``fcntl.flock`` is an advisory kernel lock available on both Linux and macOS.
Keeping it in this small wrapper lets the POSIX shell build scripts hold the
lock for their complete lifetime without depending on a platform-specific
``flock`` command.  Hashing is likewise kept in Python's standard library so
stock macOS need not provide GNU coreutils' ``sha256sum``.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def write_manifest(directory: Path, names: list[str], output: str) -> None:
    lines = []
    for name in names:
        path = directory / name
        if Path(name).name != name or not path.is_file():
            raise ValueError(f"manifest input must be a file directly in archive: {name}")
        lines.append(f"{digest(path)}  {name}\n")
    (directory / output).write_text("".join(lines), encoding="ascii")


def check_manifest(directory: Path, manifest: str) -> None:
    failed = False
    for line in (directory / manifest).read_text(encoding="ascii").splitlines():
        try:
            expected, name = line.split("  ", 1)
            if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
                raise ValueError
            if Path(name).name != name or not name:
                raise ValueError
            actual = digest(directory / name)
        except (OSError, ValueError):
            print(f"{line}: FAILED", file=sys.stderr)
            failed = True
            continue
        if actual == expected:
            print(f"{name}: OK")
        else:
            print(f"{name}: FAILED", file=sys.stderr)
            failed = True
    if failed:
        raise SystemExit(1)


def locked(lock_path: Path, command: list[str]) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        child = subprocess.Popen(command, env=os.environ | {"ULX3S_BUILD_LOCKED": "1"})

        def forward(signum: int, _frame: object) -> None:
            if child.poll() is None:
                child.send_signal(signum)

        signal.signal(signal.SIGINT, forward)
        signal.signal(signal.SIGTERM, forward)
        return child.wait()


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="action", required=True)
    lock = commands.add_parser("lock")
    lock.add_argument("lock", type=Path)
    lock.add_argument("command", nargs=argparse.REMAINDER)
    manifest = commands.add_parser("manifest")
    manifest.add_argument("directory", type=Path)
    manifest.add_argument("output")
    manifest.add_argument("names", nargs="+")
    check = commands.add_parser("check")
    check.add_argument("directory", type=Path)
    check.add_argument("manifest")
    single = commands.add_parser("digest")
    single.add_argument("file", type=Path)
    args = parser.parse_args()
    if args.action == "lock":
        if not args.command:
            parser.error("lock command must follow --")
        return locked(args.lock, args.command)
    if args.action == "manifest":
        write_manifest(args.directory, args.names, args.output)
        return 0
    if args.action == "digest":
        print(digest(args.file))
        return 0
    check_manifest(args.directory, args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

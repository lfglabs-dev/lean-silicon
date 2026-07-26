#!/usr/bin/env python3
"""Atomically replace a result directory with a verified staged directory."""

from __future__ import annotations

import argparse
import ctypes
import errno
import os
from pathlib import Path
import shutil
import signal

AT_FDCWD = -100
RENAME_EXCHANGE = 2


def _exchange(left: Path, right: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise OSError(errno.ENOSYS, "renameat2 is unavailable")
    result = renameat2(
        AT_FDCWD, os.fsencode(left), AT_FDCWD, os.fsencode(right), RENAME_EXCHANGE
    )
    if result:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def publish(staged: Path, destination: Path) -> None:
    staged = staged.resolve()
    destination = destination.resolve()
    if not staged.is_dir() or not destination.is_dir():
        raise ValueError("staged and destination must both be directories")
    if staged.parent != destination.parent:
        raise ValueError("staged and destination must share a parent filesystem")
    _exchange(staged, destination)
    shutil.rmtree(staged)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("staged", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    pause_file = os.environ.get("ATOMIC_PUBLISH_TEST_PAUSE_FILE")
    if pause_file:
        Path(pause_file).touch()
        signal.pause()
    publish(args.staged, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

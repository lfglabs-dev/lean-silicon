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
# Darwin calls the equivalent operation RENAME_SWAP.  It deliberately has the
# same value as Linux's RENAME_EXCHANGE, but keeping a separately named
# constant makes the two ABIs and their intent explicit.
RENAME_SWAP = 2


def _exchange(left: Path, right: Path) -> None:
    """Atomically swap two same-parent directories.

    Linux provides renameat2(RENAME_EXCHANGE); macOS provides the equivalent
    renameatx_np(RENAME_SWAP).  A copy/delete fallback is intentionally not
    used: it could expose a mixed archive or lose the old archive if the
    publisher is interrupted between operations.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is not None:
        result = renameat2(
            AT_FDCWD,
            os.fsencode(left),
            AT_FDCWD,
            os.fsencode(right),
            RENAME_EXCHANGE,
        )
        if not result:
            return
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))

    # renameatx_np is the documented Darwin operation for atomically swapping
    # two directory entries.  It is available on the macOS host workflow even
    # though that platform has no Linux renameat2 symbol.
    renameatx_np = getattr(libc, "renameatx_np", None)
    if renameatx_np is not None:
        result = renameatx_np(
            AT_FDCWD,
            os.fsencode(left),
            AT_FDCWD,
            os.fsencode(right),
            RENAME_SWAP,
        )
        if not result:
            return
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))

    raise OSError(
        errno.ENOSYS,
        "atomic directory exchange requires renameat2 (Linux) or "
        "renameatx_np (macOS)",
    )


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

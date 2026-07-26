"""Regression tests for all-or-nothing ULX3S archive publication."""

from __future__ import annotations

import errno
import importlib.util
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "atomic_publish.py"
SPEC = importlib.util.spec_from_file_location("atomic_publish", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
atomic_publish = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(atomic_publish)


def snapshot(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


class AtomicPublishTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.parent = Path(self.tempdir.name)
        self.destination = self.parent / "archive"
        self.staged = self.parent / "stage"
        self.destination.mkdir()
        self.staged.mkdir()
        (self.destination / "bitstream.bit").write_bytes(b"old bitstream")
        (self.destination / "SHA256SUMS").write_bytes(b"old manifest")
        (self.staged / "bitstream.bit").write_bytes(b"new bitstream")
        (self.staged / "SHA256SUMS").write_bytes(b"new manifest")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_failed_exchange_keeps_the_complete_old_archive(self) -> None:
        old = snapshot(self.destination)
        with mock.patch.object(
            atomic_publish, "_exchange", side_effect=OSError(errno.EIO, "injected")
        ):
            with self.assertRaises(OSError):
                atomic_publish.publish(self.staged, self.destination)
        self.assertEqual(snapshot(self.destination), old)
        self.assertEqual(snapshot(self.staged)["bitstream.bit"], b"new bitstream")

    def test_mutation_guard_rejects_copy_before_exchange(self) -> None:
        """A failed swap must not have copied even one staged archive member."""
        old = snapshot(self.destination)
        with mock.patch.object(
            atomic_publish, "_exchange", side_effect=OSError(errno.EIO, "injected")
        ):
            with self.assertRaises(OSError):
                atomic_publish.publish(self.staged, self.destination)
        self.assertEqual(old, snapshot(self.destination))
        self.assertNotEqual(snapshot(self.staged), snapshot(self.destination))

    def test_interruption_before_exchange_keeps_the_complete_old_archive(self) -> None:
        old = snapshot(self.destination)
        pause_file = self.parent / "paused"
        environment = os.environ | {"ATOMIC_PUBLISH_TEST_PAUSE_FILE": str(pause_file)}
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), str(self.staged), str(self.destination)],
            env=environment,
        )
        try:
            deadline = time.monotonic() + 5
            while not pause_file.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(pause_file.exists(), "publisher did not reach interruption point")
            process.send_signal(signal.SIGTERM)
            self.assertEqual(process.wait(timeout=5), -signal.SIGTERM)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        self.assertEqual(snapshot(self.destination), old)

    def test_macos_uses_renameatx_np_when_linux_renameat2_is_absent(self) -> None:
        calls: list[tuple[object, ...]] = []

        class DarwinLibc:
            renameat2 = None

            @staticmethod
            def renameatx_np(*args: object) -> int:
                calls.append(args)
                return 0

        with mock.patch.object(atomic_publish.ctypes, "CDLL", return_value=DarwinLibc()):
            atomic_publish._exchange(self.staged, self.destination)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], atomic_publish.AT_FDCWD_DARWIN)
        self.assertEqual(calls[0][2], atomic_publish.AT_FDCWD_DARWIN)
        self.assertEqual(calls[0][-1], atomic_publish.RENAME_SWAP)

    def test_no_atomic_exchange_api_fails_without_mutating_archive(self) -> None:
        old = snapshot(self.destination)

        class NoExchangeLibc:
            renameat2 = None
            renameatx_np = None

        with mock.patch.object(atomic_publish.ctypes, "CDLL", return_value=NoExchangeLibc()):
            with self.assertRaisesRegex(OSError, "atomic directory exchange"):
                atomic_publish.publish(self.staged, self.destination)
        self.assertEqual(snapshot(self.destination), old)


if __name__ == "__main__":
    unittest.main()

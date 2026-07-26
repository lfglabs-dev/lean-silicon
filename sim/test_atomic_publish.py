import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from tools import atomic_publish

SCRIPT = Path(__file__).parents[1] / "tools" / "atomic_publish.py"


class AtomicPublishTests(unittest.TestCase):
    def make_archives(self, root):
        old = root / "archive"
        staged = root / ".archive-staged"
        old.mkdir()
        staged.mkdir()
        (old / "artifact.bit").write_bytes(b"old-bitstream")
        (old / "SHA256SUMS").write_text("old-manifest\n")
        (staged / "artifact.bit").write_bytes(b"new-bitstream")
        (staged / "SHA256SUMS").write_text("new-manifest\n")
        return old, staged

    def test_success_replaces_the_complete_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, staged = self.make_archives(Path(tmp))
            atomic_publish.publish(staged, old)
            self.assertEqual((old / "artifact.bit").read_bytes(), b"new-bitstream")
            self.assertEqual((old / "SHA256SUMS").read_text(), "new-manifest\n")
            self.assertFalse(staged.exists())

    def test_exchange_failure_preserves_the_complete_old_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, staged = self.make_archives(Path(tmp))
            with mock.patch.object(
                atomic_publish, "_exchange", side_effect=OSError("injected failure")
            ):
                with self.assertRaises(OSError):
                    atomic_publish.publish(staged, old)
            self.assertEqual((old / "artifact.bit").read_bytes(), b"old-bitstream")
            self.assertEqual((old / "SHA256SUMS").read_text(), "old-manifest\n")
            self.assertEqual((staged / "artifact.bit").read_bytes(), b"new-bitstream")

    def test_termination_before_exchange_preserves_old_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old, staged = self.make_archives(root)
            paused = root / "paused"
            env = os.environ.copy()
            env["ATOMIC_PUBLISH_TEST_PAUSE_FILE"] = str(paused)
            process = subprocess.Popen(
                [sys.executable, str(SCRIPT), str(staged), str(old)], env=env
            )
            for _ in range(200):
                if paused.exists():
                    break
                time.sleep(0.01)
            self.assertTrue(paused.exists(), "publisher did not reach test pause")
            process.terminate()
            self.assertNotEqual(process.wait(timeout=5), 0)
            self.assertEqual((old / "artifact.bit").read_bytes(), b"old-bitstream")
            self.assertEqual((old / "SHA256SUMS").read_text(), "old-manifest\n")

    def test_shared_builds_lock_before_taking_their_snapshot(self):
        root = Path(__file__).parents[1]
        for name in ("build_smoke.sh", "build_uart.sh"):
            script = (root / "fpga" / "ulx3s" / name).read_text()
            lock = script.index('"$SUPPORT" lock "$LOCK"')
            snapshot = script.index('cp -a "$OUTDIR/." "$STAGE/"')
            self.assertLess(lock, snapshot, f"{name} snapshots before locking")
            self.assertNotIn("flock 9", script, f"{name} requires Linux flock(1)")


if __name__ == "__main__":
    unittest.main()

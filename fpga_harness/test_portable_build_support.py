"""Board-free regression tests for macOS-compatible ULX3S build support."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "tools" / "portable_build_support.py"


class PortableBuildSupportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.work = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def command(self, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SUPPORT), *args], text=True, capture_output=True, **kwargs
        )

    def test_digest_manifest_detects_mutation_without_sha256sum(self) -> None:
        archive = self.work / "archive"
        archive.mkdir()
        (archive / "artifact.bit").write_bytes(b"original")
        self.assertEqual(self.command("manifest", str(archive), "SHA256SUMS", "artifact.bit").returncode, 0)
        self.assertEqual(self.command("check", str(archive), "SHA256SUMS").returncode, 0)
        (archive / "artifact.bit").write_bytes(b"mutated")
        broken = self.command("check", str(archive), "SHA256SUMS")
        self.assertNotEqual(broken.returncode, 0)
        self.assertIn("artifact.bit: FAILED", broken.stderr)

    def test_check_rejects_an_empty_manifest(self) -> None:
        archive = self.work / "archive"
        archive.mkdir()
        (archive / "SHA256SUMS").write_text("", encoding="ascii")

        result = self.command("check", str(archive), "SHA256SUMS")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA256SUMS: FAILED (no well-formed checksum entries)", result.stderr)

    def test_check_rejects_manifest_with_no_well_formed_entries(self) -> None:
        archive = self.work / "archive"
        archive.mkdir()
        (archive / "SHA256SUMS").write_text("not a checksum entry\n", encoding="ascii")

        result = self.command("check", str(archive), "SHA256SUMS")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA256SUMS: FAILED (no well-formed checksum entries)", result.stderr)

    def test_lock_is_cross_process_and_released_after_interruption(self) -> None:
        lock = self.work / "publish.lock"
        marker = self.work / "started"
        sleeper = self.work / "sleeper.py"
        sleeper.write_text(
            "from pathlib import Path\nimport sys,time\nPath(sys.argv[1]).touch()\ntime.sleep(30)\n",
            encoding="utf-8",
        )
        process = subprocess.Popen(
            [sys.executable, str(SUPPORT), "lock", str(lock), "--", sys.executable, str(sleeper), str(marker)]
        )
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(marker.exists(), "lock holder did not start")
            blocked = subprocess.Popen(
                [sys.executable, str(SUPPORT), "lock", str(lock), "--", sys.executable, "-c", "raise SystemExit(0)"],
            )
            time.sleep(0.1)
            self.assertIsNone(blocked.poll(), "second publisher acquired a held lock")
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=5)
            self.assertEqual(blocked.wait(timeout=5), 0)
        finally:
            for child in (process, locals().get("blocked")):
                if child is not None and child.poll() is None:
                    child.kill()
                    child.wait()

    def test_both_builds_run_with_failing_flock_and_sha256sum_mocks(self) -> None:
        """Reproduce a stock-macOS-like tool gap using deterministic board-free tools."""
        repo = self.work / "repo"
        shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        mocks = self.work / "mock-bin"
        mocks.mkdir()
        mock = mocks / "tool"
        mock.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib,sys\n"
            "name=pathlib.Path(sys.argv[0]).name\n"
            "if name in ('flock','sha256sum'):\n raise SystemExit('non-portable command used: '+name)\n"
            "if name == 'yosys':\n"
            " if '-V' not in sys.argv:\n  p=sys.argv[sys.argv.index('-p')+1]; out=p.split('write_json ')[1].split()[0]; pathlib.Path(out).write_text('{}')\n"
            "elif name == 'nextpnr-ecp5':\n"
            " if '--version' not in sys.argv:\n  out=sys.argv[sys.argv.index('--textcfg')+1]; pathlib.Path(out).write_text('config'); print('Max frequency for clock: 25.00 MHz')\n"
            "elif name == 'ecppack':\n"
            " if '--version' not in sys.argv:\n  pathlib.Path(sys.argv[sys.argv.index('--svf')+1]).write_text('svf'); pathlib.Path(sys.argv[-1]).write_bytes(b'bit')\n"
            "elif name == 'grep': pass\n",
            encoding="utf-8",
        )
        mock.chmod(0o755)
        for name in ("yosys", "nextpnr-ecp5", "ecppack", "flock", "sha256sum"):
            (mocks / name).symlink_to(mock.name)
        environment = os.environ | {"PATH": f"{mocks}:{os.environ['PATH']}", "OSS_CAD_BIN": "/absent"}
        for script, manifest in (("build_smoke.sh", "SHA256SUMS"), ("build_uart.sh", "SHA256SUMS_bridge.txt")):
            result = subprocess.run(
                ["/bin/sh", str(repo / "fpga" / "ulx3s" / script)],
                cwd=repo,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            verified = subprocess.run(
                [sys.executable, str(repo / "tools" / "portable_build_support.py"), "check", str(repo / "results" / "ulx3s-smoke-uart-20260725"), manifest],
                text=True,
                capture_output=True,
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)


if __name__ == "__main__":
    unittest.main()

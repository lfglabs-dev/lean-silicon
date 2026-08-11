#!/usr/bin/env python3
"""Focused host-only regressions for bounded formal subprocess cleanup."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    from formal.subprocess_tree import TERMINATION_GRACE_SECONDS, run_bounded
except ModuleNotFoundError:
    from subprocess_tree import TERMINATION_GRACE_SECONDS, run_bounded


class SubprocessTreeTest(unittest.TestCase):
    def test_timeout_kills_term_resistant_descendant_within_bound(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            pid_file = Path(raw) / "btormc.pid"
            descendant = (
                "import os,signal,time,pathlib; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); "
                "time.sleep(60)"
            )
            parent = (
                "import subprocess,sys,time; "
                f"subprocess.Popen([sys.executable, '-c', {descendant!r}]); "
                "time.sleep(60)"
            )
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                run_bounded(
                    [sys.executable, "-c", parent],
                    cwd=Path(raw),
                    timeout=0.5,
                )
            elapsed = time.monotonic() - started

            self.assertLess(elapsed, 0.5 + TERMINATION_GRACE_SECONDS + 1.0)
            descendant_pid = int(pid_file.read_text())
            status = Path(f"/proc/{descendant_pid}/status")
            reap_deadline = time.monotonic() + 1.0
            while status.exists() and "State:\tZ" not in status.read_text():
                if time.monotonic() >= reap_deadline:
                    self.fail("descendant remained executable after process-group SIGKILL")
                time.sleep(0.01)
            if status.exists():
                # A killed orphan may briefly remain as a zombie until PID 1
                # reaps it; that state cannot execute or retain solver memory.
                self.assertIn("State:\tZ", status.read_text())


if __name__ == "__main__":
    unittest.main()

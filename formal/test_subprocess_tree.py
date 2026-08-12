#!/usr/bin/env python3
"""Focused host-only regressions for bounded formal subprocess cleanup."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    from formal.subprocess_tree import TERMINATION_GRACE_SECONDS, run_bounded
except ModuleNotFoundError:
    from subprocess_tree import TERMINATION_GRACE_SECONDS, run_bounded


class SubprocessTreeTest(unittest.TestCase):
    def assert_process_stopped(self, pid: int, message: str) -> None:
        status = Path(f"/proc/{pid}/status")
        reap_deadline = time.monotonic() + 1.0
        while status.exists():
            try:
                contents = status.read_text()
            except (FileNotFoundError, ProcessLookupError):
                return
            if "State:\tZ" in contents:
                return
            if time.monotonic() >= reap_deadline:
                self.fail(message)
            time.sleep(0.01)

    def test_process_disappearing_during_status_read_is_stopped(self) -> None:
        with (
            mock.patch.object(Path, "exists", return_value=True),
            mock.patch.object(Path, "read_text", side_effect=ProcessLookupError),
        ):
            self.assert_process_stopped(
                123456789,
                "a process that disappeared during observation was not stopped",
            )

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
            self.assert_process_stopped(
                descendant_pid,
                "descendant remained executable after process-group SIGKILL",
            )

    def test_timeout_kills_redirected_descendant_after_parent_exits(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            pid_file = Path(raw) / "btormc-redirected.pid"
            descendant = (
                "import os,signal,time,pathlib; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); "
                "time.sleep(60)"
            )
            parent = (
                "import subprocess,sys,time; "
                "subprocess.Popen("
                f"[sys.executable, '-c', {descendant!r}], "
                "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
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

            self.assertGreaterEqual(elapsed, 0.5 + TERMINATION_GRACE_SECONDS)
            self.assertLess(elapsed, 0.5 + TERMINATION_GRACE_SECONDS + 1.0)
            descendant_pid = int(pid_file.read_text())
            self.assert_process_stopped(
                descendant_pid,
                "redirected descendant survived process-group SIGKILL",
            )


if __name__ == "__main__":
    unittest.main()

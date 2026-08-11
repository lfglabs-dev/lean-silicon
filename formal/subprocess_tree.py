#!/usr/bin/env python3
"""Run a command with a wall-clock timeout that kills its full process tree."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path


TERMINATION_GRACE_SECONDS = 2.0


def run_bounded(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """Capture a command and bound its complete POSIX process group.

    SymbiYosys launches engines such as btormc below its immediate child.
    ``subprocess.run(timeout=...)`` only waits for the direct child and does not
    terminate that tree.  Starting a new session gives the job its own process
    group, which is terminated and then killed as a unit on timeout.
    """
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        _signal_group(process.pid, signal.SIGTERM)
        kill_deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
        try:
            output, _ = process.communicate(timeout=TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        else:
            # The direct child may exit while a solver descendant survives with
            # its output redirected. Preserve the full TERM grace period before
            # escalating the process group in that case as well.
            remaining_grace = kill_deadline - time.monotonic()
            if remaining_grace > 0:
                time.sleep(remaining_grace)
        _signal_group(process.pid, signal.SIGKILL)
        output, _ = process.communicate()
        raise subprocess.TimeoutExpired(
            list(command), timeout, output=output
        ) from error
    return subprocess.CompletedProcess(list(command), process.returncode, output, None)


def _signal_group(process_group: int, sig: signal.Signals) -> None:
    try:
        os.killpg(process_group, sig)
    except ProcessLookupError:
        pass

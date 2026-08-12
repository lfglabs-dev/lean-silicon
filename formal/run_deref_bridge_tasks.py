#!/usr/bin/env python3
"""Run every full DEREF bridge task serially."""

from pathlib import Path

try:
    from formal.subprocess_tree import run_bounded
except ModuleNotFoundError:
    from subprocess_tree import run_bounded


HERE = Path(__file__).resolve().parent
SBY = HERE / "full_lsc1_deref_bridge.sby"
# Seven serialized deep tasks leave room for the later 117-minute fail-closed
# mutation ceiling inside the workflow's 180-minute job timeout.
TASK_TIMEOUT_SECONDS = 180


def tasks(config: Path = SBY) -> list[str]:
    discovered: list[str] = []
    in_tasks = False
    for raw_line in config.read_text().splitlines():
        line = raw_line.strip()
        if line == "[tasks]":
            in_tasks = True
        elif in_tasks and line.startswith("["):
            break
        elif in_tasks and line and not line.startswith("#"):
            discovered.append(line)
    if not discovered:
        raise RuntimeError(f"no tasks found in {config}")
    return discovered


def main() -> None:
    for task in tasks():
        result = run_bounded(
            ["sby", "-f", SBY.name, task],
            cwd=HERE,
            timeout=TASK_TIMEOUT_SECONDS,
        )
        print(result.stdout, end="")
        result.check_returncode()


if __name__ == "__main__":
    main()

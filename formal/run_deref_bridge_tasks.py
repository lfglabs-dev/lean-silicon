#!/usr/bin/env python3
"""Run selected full DEREF bridge tasks serially with a fail-closed bound."""

import argparse

from pathlib import Path

try:
    from formal.subprocess_tree import run_bounded
except ModuleNotFoundError:
    from subprocess_tree import run_bounded


HERE = Path(__file__).resolve().parent
SBY = HERE / "full_lsc1_deref_bridge.sby"
# Match the independently checked lifecycle baselines. CI gives each canonical
# task its own matrix job, so this bound cannot accumulate across seven tasks.
TASK_TIMEOUT_SECONDS = 540


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


def main(selected_tasks: list[str] | None = None) -> None:
    declared_tasks = tasks()
    chosen_tasks = declared_tasks if selected_tasks is None else selected_tasks
    unknown = sorted(set(chosen_tasks) - set(declared_tasks))
    if unknown:
        raise ValueError(f"unknown task(s): {', '.join(unknown)}")
    for task in chosen_tasks:
        result = run_bounded(
            ["sby", "-f", SBY.name, task],
            cwd=HERE,
            timeout=TASK_TIMEOUT_SECONDS,
        )
        print(result.stdout, end="")
        result.check_returncode()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task", action="append", dest="selected_tasks",
        help="run only this declared task (repeatable); default: every task",
    )
    arguments = parser.parse_args()
    main(arguments.selected_tasks)

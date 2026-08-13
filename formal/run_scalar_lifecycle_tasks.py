#!/usr/bin/env python3
"""Run independently checkable scalar lifecycle obligations with hard timeouts."""

import argparse
from pathlib import Path

try:
    from formal.subprocess_tree import run_bounded
except ModuleNotFoundError:
    from subprocess_tree import run_bounded

HERE = Path(__file__).resolve().parent
SBY = HERE / "scalar_lifecycle.sby"
TASK_TIMEOUT_SECONDS = 540


def tasks() -> list[str]:
    lines = SBY.read_text().splitlines()
    start = lines.index("[tasks]") + 1
    end = lines.index("[options]")
    return [line.strip() for line in lines[start:end] if line.strip()]


def main(selected: list[str] | None = None) -> None:
    declared = tasks()
    chosen = declared if selected is None else selected
    unknown = sorted(set(chosen) - set(declared))
    if unknown:
        raise ValueError(f"unknown task(s): {', '.join(unknown)}")
    for task in chosen:
        result = run_bounded(
            ["sby", "-f", SBY.name, task], cwd=HERE,
            timeout=TASK_TIMEOUT_SECONDS,
        )
        print(result.stdout, end="")
        result.check_returncode()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", action="append", dest="selected")
    args = parser.parse_args()
    main(args.selected)

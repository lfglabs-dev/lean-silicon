#!/usr/bin/env python3
"""Run every full DEREF bridge task serially."""

from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
SBY = HERE / "full_lsc1_deref_bridge.sby"


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
        subprocess.run(["sby", "-f", SBY.name, task], cwd=HERE, check=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Extract the final Yosys cell inventory used by the Blender study."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results/m2-20260725T022000Z/m2-controller-synthesis.log"
BASE_COMMIT = "618b39923862e660589cc6258e258783904b3861"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_inventory(path: Path = SOURCE) -> dict[str, int]:
    """Return the last complete final-stat primitive inventory."""
    text = path.read_text(errors="replace")
    blocks = re.findall(
        r"(\d+)\s+cells\s*\n((?:.*\$_[A-Z0-9_]+\s*\n)+)", text
    )
    if not blocks:
        raise ValueError(f"no final Yosys cell-stat block in {path}")
    declared, body = blocks[-1]
    cells = {
        cell_type: int(count)
        for count, cell_type in re.findall(r"(\d+)\s+(\$_[A-Z0-9_]+)", body)
    }
    if sum(cells.values()) != int(declared):
        raise ValueError(
            f"inventory sum {sum(cells.values())} != declared total {declared}"
        )
    return dict(sorted(cells.items()))


def manifest() -> dict:
    cells = extract_inventory()
    return {
        "schema": "lean-silicon.blender-physical-study.inventory.v1",
        "base_commit": BASE_COMMIT,
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": sha256(SOURCE),
        "interpretation": (
            "Final flattened Yosys generic-cell statistics after ABC; this is "
            "logical inventory, not a SKY130 library mapping or physical netlist."
        ),
        "cell_total": sum(cells.values()),
        "cell_types": cells,
    }


def main() -> None:
    print(json.dumps(manifest(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verify checked-in Blender-study artifacts without Blender."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from PIL import Image
from inventory import extract_inventory, manifest

HERE = Path(__file__).resolve().parent
OUT = HERE / "artifacts"
EXPECTED = {
    "hero_4k.png": (3840, 2160),
    "exploded_stack.png": (3840, 2160),
    "top_view.png": (2400, 2400),
    "close_up.png": (2560, 1440),
    "hero_transparent.png": (3840, 2160),
    "contact_sheet.jpg": (1920, 1080),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert sum(extract_inventory().values()) == 167885
    saved = json.loads((HERE / "provenance.json").read_text())
    assert saved["inventory"] == manifest()
    for name, dimensions in EXPECTED.items():
        path = OUT / name
        assert path.stat().st_size > 10_000, path
        with Image.open(path) as image:
            assert image.size == dimensions, (name, image.size)
    sums = {}
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        sums[name] = digest
    for name, digest in sums.items():
        assert sha(HERE / name) == digest, name
    video = OUT / "orbit.mp4"
    if video.exists():
        assert video.stat().st_size > 10_000
    print(f"verified {len(sums)} hashes, {len(EXPECTED)} images, and 167885 cells")


if __name__ == "__main__":
    main()

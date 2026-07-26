#!/usr/bin/env python3
import json
import platform
from pathlib import Path
from inventory import manifest

HERE = Path(__file__).resolve().parent
data = {
    "schema": "lean-silicon.blender-physical-study.provenance.v1",
    "demo_only": True,
    "merge_permitted": False,
    "generator": "generate.py",
    "blender": "4.2.9 LTS",
    "render_engine": "BLENDER_EEVEE_NEXT",
    "python_host": platform.python_version(),
    "notice": "CONCEPTUAL · SKY130-INFORMED · NOT GDS/P&R",
    "inventory": manifest(),
}
(HERE / "provenance.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

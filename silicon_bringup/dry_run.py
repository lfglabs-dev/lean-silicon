#!/usr/bin/env python3
"""Emit a deterministic, explicitly non-hardware LSC-1u bring-up receipt."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from .bringup import receipt, validate_receipt

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    document = receipt()
    validate_receipt(document)
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output:
        if args.output.exists(): parser.error("refusing to overwrite receipt")
        args.output.write_text(encoded)
    else: print(encoded, end="")
    return 0
if __name__ == "__main__": raise SystemExit(main())

#!/usr/bin/env python3
"""Copy the allowlisted exact-run artifacts into a deterministic bundle."""

from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
from shutil import copyfile


PAYLOADS = {
    "tt_submission/tt_submission/tt_um_lfglabs_lsc1u.gds": "artifacts/tt_um_lfglabs_lsc1u.gds",
    "tt_submission/tt_submission/tt_um_lfglabs_lsc1u.oas": "artifacts/tt_um_lfglabs_lsc1u.oas",
    "tt_submission/tt_submission/tt_um_lfglabs_lsc1u.v": "artifacts/tt_um_lfglabs_lsc1u.v",
    "tt_submission/tt_submission/pdk.json": "artifacts/pdk.json",
    "precheck_reports/drc_beol.xml": "artifacts/precheck/drc_beol.xml",
    "precheck_reports/drc_feol.xml": "artifacts/precheck/drc_feol.xml",
    "precheck_reports/drc_nwell_urpm.xml": "artifacts/precheck/drc_nwell_urpm.xml",
    "precheck_reports/drc_offgrid.xml": "artifacts/precheck/drc_offgrid.xml",
    "precheck_reports/drc_pin_label_purposes_overlapping_drawing.xml": "artifacts/precheck/drc_pin_label_purposes_overlapping_drawing.xml",
    "precheck_reports/drc_zero_area.xml": "artifacts/precheck/drc_zero_area.xml",
    "precheck_reports/magic_drc.txt": "artifacts/precheck/magic_drc.txt",
    "precheck_reports/results.md": "artifacts/precheck/results.md",
    "precheck_reports/results.xml": "artifacts/precheck/results.xml",
    "gatelevel_test_results/results.xml": "artifacts/gatelevel-results.xml",
}


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    copied = []
    for source_name, output_name in sorted(PAYLOADS.items(), key=lambda item: item[1]):
        source = args.source / source_name
        if not source.is_file():
            raise SystemExit(f"required artifact is missing: {source}")
        target = args.output / output_name
        target.parent.mkdir(parents=True, exist_ok=True)
        copyfile(source, target)
        copied.append(target)

    sums = "".join(
        f"{sha256(path.read_bytes()).hexdigest()}  {path.relative_to(args.output).as_posix()}\n"
        for path in sorted(copied)
    )
    (args.output / "SHA256SUMS.txt").write_text(sums)


if __name__ == "__main__":
    main()

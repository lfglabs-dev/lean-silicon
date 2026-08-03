# v0.1 reproducibility record

## Exact source and CI

- Source commit: `6f45fd663792f1329036829c1670cefd78d66630`
- Source tree: `1ffca601b105272bdbda5edb51a6c076dc4c328b`
- GDS run: <https://github.com/lfglabs-dev/lean-silicon/actions/runs/30822256296>
- Runner for GDS, precheck, gate-level test, viewer, and release bundle:
  `ubuntu-24.04`
- PDK: `sky130A` (the exact PDK source/version are also recorded in the
  bundled `pdk.json`)
- Cocotb: `2.0.1` from `test/requirements.txt`

## Pinned action refs

The exact-main GDS workflow used these four action entry points at the same
immutable commit:

| Lane | Action ref |
|---|---|
| GDS | `TinyTapeout/tt-gds-action@30d38a7dfc6fda561d452b196fc822af0332ec23` |
| precheck | `TinyTapeout/tt-gds-action/precheck@30d38a7dfc6fda561d452b196fc822af0332ec23` |
| gate-level test | `TinyTapeout/tt-gds-action/gl_test@30d38a7dfc6fda561d452b196fc822af0332ec23` |
| viewer | `TinyTapeout/tt-gds-action/viewer@30d38a7dfc6fda561d452b196fc822af0332ec23` |

The release workflow additionally pins checkout, Python setup, Ciel PDK setup,
and artifact upload by full commit SHA. It queries the latest successful `gds`
workflow run on `main`, records the selected run and head, verifies the selected
head is the checked-out `main`, reruns the deterministic Cocotb RTL and
gate-level suites, and hashes the assembled evidence.

## Deterministic bundle regeneration

Run `python3 tools/prepare_release_bundle.py --source <download-directory>
--output <output-directory>`, where the source is the directory produced by
`gh run download RUN_ID`. The script admits only the named payload files,
copies bytes without transformation, and writes a sorted `SHA256SUMS.txt`.
Two runs from the same downloaded source must compare byte-for-byte.

The 2026-08-03 refresh performed that assembly in two separate clean detached
worktrees and obtained a byte-identical payload. Exact commands, versions,
timestamps, hashes, and exclusions are recorded in `REFRESH_RECEIPT.md`.

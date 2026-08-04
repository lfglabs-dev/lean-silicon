# PR #36 refresh receipt

## Immutable inputs

- Refresh date: `2026-08-03` (UTC)
- Exact `main` head: `6f45fd663792f1329036829c1670cefd78d66630`
- Exact `main` tree: `1ffca601b105272bdbda5edb51a6c076dc4c328b`
- Exact-main GDS workflow: `30822256296`, completed success
- GDS job: `91714841764`, success
- precheck job: `91716914341`, success
- gate-level job: `91716914247`, success
- viewer job: `91716914474`, success
- Frozen upstream oracle: `c308034ab78619b39a59d26f3dc60e7df5b52649`

## Tools and validation

- Python `3.12.3`; Cocotb `2.0.1`; pytest `8.4.2`; PyYAML `6.0.2`; jsonschema `4.25.1`
- Icarus Verilog `12.0 (stable)`
- Rust/Cargo `1.88.0`
- Lean `4.32.1`, commit `f054605aea4b840552cca2e725580bffd1e1b704`; Lake `5.0.0-src+f054605`
- Git `2.43.0`; GitHub CLI `2.86.0`; GNU Make `4.3`
- `make check`: exit 0, `2026-08-03T15:23:41Z` to `2026-08-03T15:24:02Z`; 290 Python tests passed plus repository consistency, smoke, boundary, harness, and checksum gates.
- `LEANVM_B_UPSTREAM=<clean-c308034> make sim m2-differential conformance-differential`: exit 0, `2026-08-03T15:25:01Z` to `2026-08-03T15:25:30Z`; SystemVerilog suites passed, 64 Cargo-vetted M2 RTL cases passed, and 18 corpus/10 live differential cases passed.
- `make -C test -f Makefile.tt clean && make -C test -f Makefile.tt && ! grep -q failure test/results.xml`: exit 0, `2026-08-03T15:25:30Z` to `2026-08-03T15:25:32Z`; Cocotb 5/5 passed.
- `make lean`: exit 0, `2026-08-03T15:25:43Z` to `2026-08-03T15:26:07Z`.
- The exact-main check suite independently completed all nine jobs successfully: executable models, SystemVerilog, Lean, formal/lint, Tiny Tapeout RTL, GDS, precheck, gate-level, and viewer.

## Double regeneration

Two separate clean detached worktrees ran:

```text
python3 tools/prepare_release_bundle.py --source <exact-main-run-30822256296> --output <run>
cp release/v0.1/{MANIFEST.json,PINOUT.md,REPRODUCIBILITY.md,CLAIMS.md,INFO.yaml.example,REFRESH_RECEIPT.md} <run>/
find <run> -type f ! -name SHA256SUMS.txt -print0 | sort -z | xargs -0 sha256sum > <run>/SHA256SUMS.txt
diff -ru <run-a> <run-b>
sha256sum -c <run-a>/SHA256SUMS.txt
```

Both source states were clean and at the same refresh commit/tree. `diff -ru`
returned 0, and every generated checksum verified. The release-defined GDS,
OAS, synthesized netlist, precheck, gate-level, manifest, and checksum outputs
were byte-identical between runs.

## Bounded exclusions

- No local `sby` executable or registered formal-build wrapper was available;
  formal certification is therefore the immutable successful exact-main job
  `91714843422` and must be rerun by independent exact-head CI after push.
- No registered FPGA-build wrapper was available, and this environment lacks
  `nextpnr-ecp5` and `ecppack`. The separately defined ULX3S `.bit`, `.config`,
  and `.svf` recipes were not regenerated; no FPGA reproducibility claim is
  made by this release bundle.
- No hardware, JTAG, UART, flash, SRAM load, publication, submission, tag,
  release, or merge operation was performed.

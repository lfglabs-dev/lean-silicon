# LSC-1u Tiny Tapeout bring-up kit

This kit targets only the implemented `tt_um_lfglabs_lsc1u` wrapper. It is not
a full LSC-1 or ULX3S packet-interface driver. Its four deterministic vectors
exercise SET, XOR, GF(2^128) MUL (including reduction `0x87`), pin STATUS,
FAULT, the final-response `DONE_PULSE` (called **RETIRE** in this kit), and
the return to `RX_READY`/not-`BUSY` IDLE.

The active wrapper's mapping is source-grounded in
[`../src/tt_um_lfglabs_lsc1u.sv`](../src/tt_um_lfglabs_lsc1u.sv): byte input
is `ui_in`, byte output is `uo_out`; `uio[0]` is RX_VALID, `[1]` RX_READY,
`[2]` TX_VALID, `[3]` TX_READY, `[4]` BUSY, `[5]` FAULT, and `[7]` DONE_PULSE.
Its enabled direction mask is `0xb6`. Crucially, **`uio[6]` is reserved and
ignored**: it is not an abort pin. A partial operation is synchronously
aborted by `rst_n=0` or `ena=0`; deselection also drives outputs and the output
enable mask low. The tests cover both abort paths and prove that driving bit 6
does not create a false abort claim.

## Run it

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest silicon_bringup.test_bringup -v
PYTHONDONTWRITEBYTECODE=1 python3 -m silicon_bringup.dry_run > /tmp/lsc1u-dry-run-receipt.json
python3 -m json.tool silicon_bringup/receipt.schema.json >/dev/null
```

`dry_run.py` is a deterministic Python pin-model fixture, not a board adapter.
Every receipt it emits says `kind: dry-run` and `real_silicon: false`. It has
no serial, GPIO, FPGA-loader, or fabricated-silicon code, and therefore cannot
be used to claim hardware execution. The machine-readable contract is
[`receipt.schema.json`](receipt.schema.json); `--output` refuses to overwrite
an existing receipt.

A future physical transport must implement the ready/valid pin protocol and
produce a receipt with `kind: hardware` and `real_silicon: true`, together with
independent board provenance. That is intentionally outside this PR.

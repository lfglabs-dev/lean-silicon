# Historical ULX3S physical-validation record

This record preserves the auditable boundary for the physical ULX3S
packet/transaction-path exercise cited by the status ledger. It is scoped
validation evidence, not a proof of the current v1 packet endpoint, full
LSC-1, or fabricated silicon.

The run used one ULX3S with an ECP5 LFE5U-85F. The maintained UART image was
loaded to volatile SRAM and exercised through the host driver; each recorded
response was compared with the independent host oracle. The run covered the
supported arithmetic transaction prefix and stopped before unsupported control
flow. It therefore establishes that the documented board, transport, image,
and host-oracle path worked for that scope only.

The immutable historical record is retained in repository commit
[`762505b`](https://github.com/lfglabs-dev/lean-silicon/tree/762505b):

- `results/fpga-pr16-pr19-20260726/README.md` records the board identity,
  source revision, tool environment, image identities, loader observation, and
  request/response-oracle results;
- `results/fpga-pr16-pr19-20260726/program-run.json` is the recorded host-run
  log; and
- `results/ulx3s-smoke-uart-20260725/ulx3s_bridge.bit` is the archived,
  checksum-identified image used by that record.

The current source-built ULX3S artifacts remain separately described in
[`ULX3S_SMOKE_AND_UART.md`](ULX3S_SMOKE_AND_UART.md). A later physical run must
record its own image, source revision, environment, and oracle log before it
extends this claim.

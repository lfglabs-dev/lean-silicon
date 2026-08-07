# Historical ULX3S physical-validation record

This record preserves the auditable boundary for a historical physical ULX3S
exercise of the fixed-length MinCore arithmetic path. It is scoped validation
evidence, not evidence for the current LSC-1 v1 packet endpoint, full LSC-1,
or fabricated silicon.

The run used one ULX3S with an ECP5 LFE5U-85F. The fixed-length
`ulx3s_bridge.bit` MinCore UART image was loaded to volatile SRAM and exercised
through the MinCore host driver; each recorded response was compared with the
independent MinCore host oracle. The run covered supported arithmetic operations
and stopped before unsupported control flow. It therefore establishes that the
documented board, transport, image, and MinCore arithmetic path worked for that
scope only.

The immutable historical record is retained in repository commit
[`762505b`](https://github.com/lfglabs-dev/lean-silicon/tree/762505b):

- `results/fpga-pr16-pr19-20260726/README.md` records the board identity,
  source revision, tool environment, image identities, loader observation, and
  request/response-oracle results;
- `results/fpga-pr16-pr19-20260726/program-run.json` is the recorded MinCore
  host-run log; and
- `results/ulx3s-smoke-uart-20260725/ulx3s_bridge.bit` is the archived,
  checksum-identified image used by that record.

The fixed-length MinCore image and protocol are separately described in
[`ULX3S_SMOKE_AND_UART.md`](ULX3S_SMOKE_AND_UART.md) and
[`MINCORE_UART_HOST.md`](MINCORE_UART_HOST.md). The LSC-1 packet endpoint uses
a distinct top, artifact, and driver; no physical packet-mode receipt is cited
here. A later physical run must record its exact packet-mode artifact, source
revision, environment, and oracle log before it can establish that claim.

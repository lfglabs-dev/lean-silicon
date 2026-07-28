# Bounded frontend accepted-path partitions

Immutable starting source: `fb3c063ca280e71f8721fefe858d10ce8cca772a`.
This receipt is intentionally a bounded composed milestone, not a release
sequential-equivalence or ASIC-readiness claim.

## Commands and outcome

`tools/run_arch_state_milestones.sh results/frontend-bounded-path-20260728`
exited `0` in `13.93` seconds on Yosys 0.33. Its saved logs record successful
receiver-reset, STATUS-acceptance, and stalled INFO-response serializer formal
gates, plus focused RTL, executable boundary, differential, and mutation
gates. The standalone measured formal durations were 6.04 seconds for STATUS
acceptance and under one second for response serialization.

The STATUS acceptance proof uses its exact wire CRC `1c4eb229`; the INFO
serializer proof checks CRC `0e7bf94b` and two fixed ready-low cycles.
`SHA256SUMS` covers every captured log, and `versions-and-inputs.log` records
the exact source tree used by the runner.

## Claim boundary and remaining block

The formal partitions use actual shipped RX and TX RTL and `sat -verify`; no
cutpoint, black box, symbolic bridge, disabled check, or timeout-as-PASS is
used. The full frontend SET simulation connects accepted input, controller
decode/compute, response construction, and a 12-cycle output stall.

This does **not** prove the controller connection for all inputs, arbitrary or
unbounded backpressure, reset for the full frontend harness, release
sequential equivalence, or ASIC readiness. The unresolved release-equivalence
diagnostic remains an explicit BLOCK.

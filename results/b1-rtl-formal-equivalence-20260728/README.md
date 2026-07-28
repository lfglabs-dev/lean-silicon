# Phase B1 RTL formal/equivalence evidence

This is Phase-B evidence for the RTL packet boundary only.  It is **not** an
ASIC-readiness, sign-off, netlist, PPA, or hardware-execution claim.

## Frozen source anchor

The upstream ref was independently fetched from
`https://github.com/lfglabs-dev/lean-silicon.git` on 2026-07-28:

* `refs/heads/main = fda85f5efc6f5b460d72204b4d9c0d882960ec29`
* `fda85f5efc6f5b460d72204b4d9c0d882960ec29^{tree} = df42a6211828d856e9a21ba61ecc2cd1b9dc4e71`

The production RTL read by these checks is unchanged from that anchor:
`git diff --exit-code fda85f5efc6f5b460d72204b4d9c0d882960ec29 -- asic_core/rtl`.
Harnesses, runner, and receipts are the only additions in this B1 branch.

## Machine-checked properties

1. `b1_packet_tx_equiv_formal.sv` proves the complete, accepted-beat sequence
   for the frozen Python-model response vector
   `5a 01 84 02 00 de ad 3f 53 26 88`.  The reference is the v1 response
   envelope in `docs/LSC1_PROTOCOL.md`; the CRC is independently frozen from
   the model's IEEE CRC-32 calculation.  cvc5 BMC passes through depth 16.
2. `b1_packet_rx_fault_formal.sv` proves that a valid `0x00` first request
   byte produces `BAD_SOF (0x80)` in the production receiver.  cvc5 BMC passes
   through depth 6.
3. `b1_packet_equiv_tb.sv` exercises that same response with a stall before
   every byte, checking valid/data stability, exact bytes, completion, and the
   payload CRC.  Icarus simulation passes.

The full closed-frame receiver harness,
`b1_packet_rx_equiv_formal.sv`, is retained as a review target (good frame,
bad CRC, and CRC-before-version precedence), but was not claimed as a passing
proof: this local cvc5 1.1.2 run exceeded its 55-second cap while unrolling
three 32-bit CRC datapaths.  It is deliberately neither disabled nor weakened.

## Counterexample sensitivity

The runner copies the TX harness to a temporary directory and changes only its
expected CRC byte from `3f` to `3e`.  `tx-mutation.log` records the expected
`Status: FAILED` assertion at the altered expectation (exit 1).  The source
tree retains no mutation.

## Reproduction and receipts

From this branch root, run:

```sh
formal/b1_run.sh
sha256sum -c results/b1-rtl-formal-equivalence-20260728/SHA256SUMS
```

The runner records tool provenance in `toolchain.txt`, elaboration logs,
formal results, simulation output, and the mutation failure.  Its commands are:

```sh
yosys -s formal/b1_packet_tx_equiv.ys
yosys-smtbmc -s cvc5 --presat --noprogress -t 16 formal/b1_packet_tx_equiv.smt2
yosys -s formal/b1_packet_rx_fault.ys
yosys-smtbmc -s cvc5 --presat --noprogress -t 6 formal/b1_packet_rx_fault.smt2
iverilog -g2012 -Wall -s b1_packet_equiv_tb ... && vvp ...
```

Receipt SHA-256 values are in `SHA256SUMS`; all entries verify with the command
above.  `tested-commit.txt` and `tested-tree.txt` record the exact anchor used
before this evidence commit.

## Boundaries and independent review

These checks do not prove arbitrary response payload/status combinations,
unbounded backpressure, successful request parsing, full CRC equivalence,
controller/transaction semantics, ISA conformance, synthesis, timing, power,
or hardware behavior.  A reviewer should independently verify the anchor and
hashes, rerun `formal/b1_run.sh` in a pinned formal container, complete the
retained full receiver proof with a solver/time budget appropriate for the CRC
cone, and assess the RTL-to-Python/Lean semantic bridges separately.

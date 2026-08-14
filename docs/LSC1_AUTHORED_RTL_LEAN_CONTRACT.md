# LSC1-05 authored RTL / Lean observable contract

## Gap matrix at `c7ac845d29d9661912b22ca75d3f70637f0b981a`

| Class | Canonical Lean edge already present | Authored RTL evidence already present | Gap closed here |
| --- | --- | --- | --- |
| SET/XOR/MUL | accepted v1 frame to `Effect`, CRC-bound `Transaction` stage/RETIRE | packet frontend execution and byte-exact differential tests | one checked observation vocabulary requires RESULT, stalls and RETIRE for all three |
| DEREF | all three accepted modes to canonical control primitive and effect | integrated result/retire traces plus differential success/fault cases | the same vocabulary requires RESULT, fault, stalls and RETIRE |
| JUMP | accepted taken/not-taken frame to canonical control primitive and effect | integrated result/retire traces plus differential success/fault cases | the same vocabulary requires RESULT, fault, stalls and RETIRE |
| BLAKE3 | validated request/service binding, stall, abort/reset and exactly-once retirement | authored service-required/result/retire path, retry and reset/abort tests | the same vocabulary requires service, RESULT, fault, stalls, reset/abort discard and RETIRE |
| ready/valid | Lean service stall theorems and retained scalar trace model | integrated bench asserts stable `tx_valid/tx_data` and receive exclusion under backpressure | both sides must expose the stall observations in the executable contract |
| fault/lifecycle | canonical fault decisions and atomic transaction/service state | status responses, sticky fault, `result_pending`, `service_pending`, `done_pulse` | faults, discard controls and retirement cannot disappear from either checked scope |

`LeanVMBMinCore.AuthoredRTLContract` is the common machine-checked vocabulary.
Its scope-completeness theorems prevent silently omitting an implemented opcode
or lifecycle observation. Its semantic bindings refer directly to the existing
accepted-frame decisions, `Transaction` theorems and BLAKE3 lifecycle, rather
than restating instruction results in a new model.

`python3 tools/lsc1_authored_rtl_contract.py --verify` builds that Lean module,
extracts its executable contract lines, compiles and runs the authored
`asic_core/rtl/lsc1_packet_frontend.sv` with deterministic ready/valid stalls,
executes byte-exact result/service/fault/RETIRE scenarios, and requires exact
set equality with the Lean vocabulary. The top-level unittest makes this a
repeatable repository gate.

## Deliberate boundaries

This is a finite witness-suite relation over the currently authored full LSC-1
packet endpoint. It is substantive and executable, but it is **not** an
unbounded cycle-by-cycle proof that arbitrary SystemVerilog traces refine Lean.
The byte-exact RTL checks still use the independent Python protocol companion
as the concrete vector driver; Lean supplies and proves the shared semantic
scope and its bindings, not every response byte in those RTL vectors. Input
"stall" includes receive gaps and receive exclusion while a response is held;
it does not prove arbitrary hostile `rx_valid` waveforms. No claim is made for
LSC-1µ, host fetch/memory, netlist, P&R, FPGA, or any instruction beyond the
implemented SET/XOR/MUL/DEREF/JUMP/BLAKE3 packet paths.

The remaining theorem edge is an independent full-profile cycle transition
system plus an inductive correspondence proof to the authored SV, including
arbitrary parser prefixes and every fault-precedence combination. This change
does not relabel the finite executable relation as that stronger result.

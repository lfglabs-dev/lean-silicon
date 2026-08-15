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

`LeanVMBMinCore.AuthoredRTLContract.contractHolds` is the single normative
finite relation.  Its semantic bindings refer directly to the existing
accepted-frame decisions, `Transaction` theorems and BLAKE3 lifecycle, rather
than restating instruction results in a new executable model.

`python3 tools/lsc1_authored_rtl_contract.py --verify` compiles and runs the
authored `asic_core/rtl/lsc1_packet_frontend.sv` with deterministic ready/valid
stalls.  The SystemVerilog harness emits raw `RESPONSE`, `RTL_COUNTS`, and
`RTL_CONTROL ... BEFORE/AFTER` records.  Python derives facts from those
records: response status bytes name RESULT/SERVICE_REQUIRED/FAULT/RETIRE,
handshake counters name stalls, `done_pulse` corroborates RETIRE, and actual
pending-state transitions establish reset/abort discard.  It also requires
every response byte to equal the independent executable protocol model.

The runner then writes a temporary Lean module containing only those derived
facts and asks the Lean kernel to decide `contractHolds rtlFacts`.  There is no
Python copy of the required label table and no predeclared RTL observation set.
The top-level unittest exercises this complete path as a repository gate.

## Deliberate boundaries

This is a finite witness-suite relation over the currently authored full LSC-1
packet endpoint. It is substantive and executable, but it is **not** an
unbounded cycle-by-cycle proof that arbitrary SystemVerilog traces refine Lean.
The byte-exact authored-RTL checks use the independent Python protocol companion
as the concrete finite vector driver and byte oracle; that executable-model
evidence is separate from the Lean theorem and authored-RTL simulation
evidence. Lean checks the shared finite relation and its semantic bindings; it
does not prove every response byte or import the SystemVerilog transition
system. An RX stall is recorded only when `rx_valid && !rx_ready`; each finite
witness deliberately presents a valid byte while the authored frontend is not
ready, while idle `!rx_ready` cycles are excluded. This does not prove arbitrary
hostile `rx_valid` waveforms. No claim is made for
LSC-1µ, LSC1-06+, host fetch/memory, netlist, P&R, FPGA, or any instruction beyond the
implemented SET/XOR/MUL/DEREF/JUMP/BLAKE3 packet paths.

No netlist, P&R report, FPGA run, or hardware observation is consumed by this
gate.  Consequently none of those evidence classes is upgraded by this result,
and this document makes no end-to-end hardware claim.

The remaining theorem edge is an independent full-profile cycle transition
system plus an inductive correspondence proof to the authored SV, including
arbitrary parser prefixes and every fault-precedence combination. This change
does not relabel the finite executable relation as that stronger result.

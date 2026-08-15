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

`LeanVMBMinCore.AuthoredRTLContract.contractHolds` is the single bounded
common-relation theorem.  Its result is `ContractEvidence`: exact finite fact
equality plus explicit premises for the canonical SET/XOR/MUL/DEREF/JUMP/BLAKE3
reachability witnesses, abort/reset semantics, and the general successful
RESULT-to-RETIRE theorem.  Thus equality of a generated label list alone cannot
inhabit the contract.

`python3 tools/lsc1_authored_rtl_contract.py --verify` compiles and runs the
authored `asic_core/rtl/lsc1_packet_frontend.sv` with deterministic ready/valid
stalls.  The authored RTL retains the decoded opcode owning pending service or
result state.  The SystemVerilog harness emits a raw `RESPONSE` followed by one
`RTL_TRANSACTION` record containing that RTL-derived origin opcode and counters
scoped to the same request/response interval.  Python derives facts only from
those records: response status bytes name RESULT/SERVICE_REQUIRED/FAULT;
transaction-local handshake events name stalls; and RETIRE requires status
`0x02`, a decoded RETIRE request, and exactly one `done_pulse` in that same
interval.  `RTL_CONTROL ... BEFORE/AFTER` records carry the pending operation's
RTL provenance and establish reset/abort discard.  Every response byte must
also equal the independent executable protocol model.

The runner then writes a temporary Lean module containing only those derived
facts and asks the Lean kernel to construct `ContractEvidence rtlFacts` by
applying `contractHolds` to fact equality and the named semantic theorems. There is no
Python copy of the required label table and no predeclared RTL observation set.
The top-level unittest exercises this complete path and adversarially rejects
opcode relabeling, cross-transaction stall/DONE borrowing, and multiple or
non-co-occurring DONE fabrication.

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

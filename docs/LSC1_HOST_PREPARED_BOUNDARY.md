# LSC1-06 host-prepared memory/fetch boundary

LSC1-06 closes one finite integration gap left explicit by LSC1-05: the real
host runtime fetches the checked-in frozen-compiler fixture, reads and updates
its `HostMemory`, prepares each self-contained LSC-1 transaction, and the
authored packet RTL consumes those exact bytes. The endpoint still performs no
instruction fetch and owns no VM memory.

`make lsc1-host-authored-rtl-boundary` runs the 13-instruction fixture through
the executable endpoint, requires its halted step count and final host memory
to match the recorded public result from frozen leanVM-b commit
`c308034ab78619b39a59d26f3dc60e7df5b52649`, and records every request and
response. The complete negotiation plus 13 instruction/RETIRE lifecycles is
then replayed in one authored `asic_core/rtl/lsc1_packet_frontend.sv` session.
Every instruction and retirement response byte, including cumulative retirement
state, must match the executable model. Negotiation is checked against the
authored RTL's narrower, independently specified feature mask: it advertises
interpreter-compatible semantics and BLAKE3 offload, but not the model's
forward-only profile. The only data sent between instructions is the next
host-prepared packet; the RTL receives no program image or VM-memory interface.

The generated Lean checker imports `HostPreparedBoundary` and constructs
`BoundaryEvidence` from the derived 13-step operation sequence and the checked
per-step predicates: supplied cells came from the host snapshot, results were
applied only after RETIRE, and RTL bytes matched the model. The operation list
is finite and exact; it is not a theorem over arbitrary programs.

## Claim boundary

This is executable-model evidence, a finite Lean receipt, and authored-RTL
simulation evidence. Those are separate layers. It is not an inductive
Lean-to-SystemVerilog refinement, unbounded proof, or end-to-end verification.
It consumes no synthesized netlist, P&R result, FPGA observation, or hardware
observation and makes no claim about them. LSC-1µ and LSC1-07+ are out of scope.

## First-SET RETIRE mismatch slice

`make lsc1-retire-mismatch-host-boundary` is a separate, finite regression for
fixture step 0 only. A real `HostRuntime` fetches and prepares the first
write-producing `SET_CONSTANT` from the initial `{m[0] = 1, m[1] = 0}` host
memory. The lane flips exactly bit 0 of the host-generated RETIRE `result_crc`.
It requires the host, a fresh executable endpoint, and the authored packet RTL
to leave the proposed `m[2] = 3`, `pc = 1`, `fp = 0` transition uncommitted.
The exact SET request is then staged again and the untouched host-generated
RETIRE is replayed, which must commit once. Both endpoint implementations
consume the same five recorded frames; response bytes and their observable
committed scalar states are compared independently.

This adds no general refinement or end-to-end claim. It does not exercise or
make claims about Lean semantics, netlists, P&R, FPGA, hardware, LSC-1µ, or
LSC1-07 and later work.

## First-SET RETIRE transaction-ID mismatch slice

`make lsc1-retire-txn-mismatch-host-boundary` is a distinct finite regression
for fixture step 0. A real `HostRuntime` prepares transaction 1 and the same
`SET_CONSTANT` proposal described above. The lane preserves its generated
result CRC and flips only bit 0 of the RETIRE `txn_id`, producing transaction
0. The endpoint must answer `RETIRE_MISMATCH` while echoing transaction 0 with
detail 1 and discard the staged transition. Because that echo does not match
the host's in-flight transaction 1, `HostRuntime` must reject the response as a
`ProtocolViolation`, with its memory, `pc`, and `fp` unchanged.

Independently, a fresh executable endpoint and the authored packet RTL consume
the same exact five frames: negotiate, SET, corrupt-ID RETIRE, identical SET,
and untouched host RETIRE. Their response bytes must match with statuses
`OK`, `OK`, `RETIRE_MISMATCH`, `OK`, and `RETIRED`. After frame 3 each must be
idle with no pending result, invalid committed state, `pc = fp = 0`, and
`retire_seq = 0`; after frame 5 each must be idle with no pending result, valid
committed state, `pc = 1`, `fp = 0`, and `retire_seq = 1`.

This is bounded executable-model and authored-RTL simulation evidence only.
It makes no Lean, synthesized-netlist, P&R, FPGA, hardware, LSC-1µ, unbounded,
or end-to-end claim.

## BLAKE3 SERVICE_PENDING STATUS_QUERY slice

`make lsc1-blake3-status-host-boundary` uses the full-LSC-1 `HostRuntime`
preparation path for transaction `0x10203040`, then runs exactly four lifecycle
frames: `BLAKE3_REQUEST`, `STATUS_QUERY`, its valid host-computed
`SERVICE_RESPONSE`, and the matching untouched CRC-bound `RETIRE`.
Deterministic finite RX and TX stalls are exercised. The executable endpoint
and authored RTL must return identical bytes.
The INFO payload must report SERVICE_PENDING, the same transaction ID, prior
SERVICE_REQUIRED, and zero retirement, fault, and committed state; the staged
BLAKE3 transaction and service must survive the query; the subsequent service
response must produce the result; and RETIRE must commit once.

`make lsc1-blake3-status-host-boundary-mutation` copies only the packet frontend,
removes `blake_service_pending` from STATUS transaction-ID selection, proves that
mutant compiles/elaborates, and requires the differential to kill it.

Production RTL is unchanged. This is a bounded executable-model/authored-RTL
simulation result only. Lean is unchanged, and no netlist, P&R, FPGA, hardware,
LSC-1µ, unbounded refinement, or end-to-end claim is made.

## Scalar RESULT_PENDING STATUS_QUERY slice

`make lsc1-scalar-status-host-boundary` uses the full-LSC-1 `HostRuntime` and
frozen fixture step 0 to emit exactly `NEGOTIATE`, transaction 1's
`SET_CONSTANT` proposal (`m[2] = 3`, next `pc = 1`, `fp = 0`), an inserted
`STATUS_QUERY`, and the untouched RETIRE generated by the host runtime.
Deterministic finite nonzero RX/TX stalls and blocked-byte stability are
observed. Apart from the documented NEGOTIATE feature-mask normalization, the
executable endpoint and authored RTL response frames must match byte-for-byte.

The INFO response reports RESULT_PENDING, transaction 1, prior OK, retirement
sequence and last fault zero, and invalid zero committed state. The query must
preserve the staged result CRC, next PC/FP, proposed write, and pending state,
with no commit or DONE. RETIRE then commits exactly once and produces one DONE.
`make lsc1-scalar-status-host-boundary-mutation` changes only the scalar STATUS
transaction-ID arm from `staged_txn_id` to zero in a temporary authored-RTL
copy; transaction ID zero must make the focused differential fail.

Production executable-model, Lean, and authored-RTL behavior are unchanged.
This evidence-only slice remains a finite executable-model observation, a
separate authored-RTL differential, and a targeted mutant. Lean compiles
separately and does not prove this RTL trace. Netlist, P&R, hardware, LSC-1µ,
unbounded refinement, and end-to-end claims remain excluded.

## Scalar post-RETIRE STATUS_QUERY slice

`make lsc1-scalar-post-retire-status` covers the distinct post-retirement
boundary for frozen fixture step 0. The full-LSC-1 `HostRuntime` emits exactly
`NEGOTIATE`, transaction 1's `SET_CONSTANT` proposal (`m[2] = 3`, next
`pc = 1`, `fp = 0`), its untouched matching `RETIRE`, and then an inserted
`STATUS_QUERY`. Apart from the documented NEGOTIATE feature-mask normalization,
the executable model and authored RTL responses must match byte-for-byte.

The INFO payload must report IDLE, staged transaction 0, prior status RETIRED,
`retire_seq = 1`, `last_fault = OK`, committed `pc = 1`, `fp = 0`, and
`state_valid = 1`. The query must preserve the complete captured post-retirement
committed and staged state and emit no additional DONE pulse. Deterministic
finite RX/TX stalls must produce nonzero blocked-beat stability observations.
`make lsc1-scalar-post-retire-status-mutation` copies the authored response
payload mux, changes only serialized STATUS `state_valid` to zero, proves that
the mutant compiles and elaborates, and requires this differential to reject it.

This is one finite seeded executable-model observation and a separate authored-
RTL simulation differential with a targeted mutant. Lean is only compiled by
its separate gate. It is not universal refinement, whole-design equivalence,
or end-to-end verification, and makes no netlist, P&R, FPGA, hardware, LSC-1µ,
or host fetch/memory claim.

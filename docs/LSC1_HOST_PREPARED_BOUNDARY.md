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
then replayed in one authored `asic_core/rtl/lsc1_packet_frontend.sv` session;
every response byte, including cumulative retirement state, must match the
executable model. The only data sent between instructions is the next
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

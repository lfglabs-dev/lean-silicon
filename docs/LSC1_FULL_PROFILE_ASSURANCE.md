# LSC-1 full-profile assurance lane

This is the dedicated issue #50 lane. It is deliberately outside the SKY26c
submission, release bundle, and release gates. Nothing here changes `src/`,
`release/`, GDS, tags, or the LSC-1u claim boundary.

## Pins and reproducibility

The machine-readable plan is `assurance/full-profile/plan.json`. Its source is
current `main` at commit `c89d24e75ba2cf8bfab871e1c68c738821a8681f`, tree
`d1ec337c51d736750d982a475cac668732c8a26b`. Semantic authority remains frozen
leanVM-b `c308034ab78619b39a59d26f3dc60e7df5b52649`. The assurance command hashes
every RTL input to the elaborated hierarchy, records exact `python`, Icarus and Yosys version output, writes
the generated Yosys-elaborated hierarchy snapshot only to the caller's private cache, and
records its SHA-256. The receipt therefore pins source, RTL, generated snapshot,
toolchain, commands, assumptions, outcomes, and residual gaps in one JSON file.

```sh
cache="$(mktemp -d)"
LSC1_FULL_CACHE="$cache" make full-profile-assurance
python3 -m json.tool "$cache/receipt.json"
```

The cache is mutable evidence, not a release artifact. Preserve a receipt and
the hierarchy snapshot together when reproducing a particular run. A receipt is
accepted only if the checkout descends from the plan's exact source commit/tree,
all tracked inputs are clean, the cache resolves outside the checkout, and its
permissions deny group/other access. Receipt content is deterministic for an exact checkout and toolchain;
caller-specific cache paths and timing-bearing command output are not recorded.

## State and transaction surface

The RTL retains parser state and payload bytes; transmitter state and response
bytes; arithmetic/encoder controller state; a staged result (`txn_id`, next
`pc`/`fp`, result CRC); committed `pc`, `fp`, and retire sequence; negotiated
profile; and last status/fault. Reset and ABORT dominate transfers. Exactly one
result may be pending, and only a matching RETIRE commits staged scalar state.

The implemented request surface is XOR, MUL_NATIVE, SET_CONSTANT, DEREF_CELL,
DEREF_PC, DEREF_FP, JUMP, NEGOTIATE, RETIRE, and STATUS_QUERY, including frame
faults, profile checks, absent/present cells, back-solving, pointer and inverse
checks, branch proposals, stalls, abort, and retirement. BLAKE3_REQUEST and
SERVICE_RESPONSE exist only in the executable model and are explicit gaps in
the RTL. Host memory, program fetch, trace/proof persistence, and multi-step VM
execution remain outside the endpoint.

## Classification and assumptions

There is **no unbounded full-profile proof**. The lane supplies bounded evidence:

1. seeded and adversarial byte-exact comparisons between the executable model
   and authored RTL;
2. cycle simulation of framing, stalls, response stability, ABORT, staged
   results, and one-time retirement;

Yosys also elaborates the exact RTL hierarchy into a generated snapshot whose
hash is pinned in the receipt. This is provenance evidence only. It is not
classified as synthesis, a behavioral comparison, or equivalence.

Assumptions are explicit: synchronous single clock; reset is asserted by each
testbench before traffic; inputs are two-state simulation values; accepted
beats use ready/valid; the host eventually supplies/drains the finite test
vectors; CRC is integrity, not authentication; generated netlist simulation
uses Yosys generic cells and Icarus; the seeded finite corpus is not exhaustive.
No fairness or hostile-host assumption is converted into a proof.

An unbounded claim is blocked because the repository has no complete independent
formal transition specification for the packet executor, no formal relation to
the frozen Lean/Rust semantics, and no RTL implementation of BLAKE3 service
exchange. Sequential RTL-to-gate equivalence for a physical full-profile
netlist is also blocked because no pinned physical full-profile netlist exists.

## Non-vacuity and mutations

The cycle test witnesses successful SET, XOR, MUL, DEREF variants, JUMP,
NEGOTIATE, STATUS and RETIRE responses, plus faults and ABORT. Differential
tests require nonempty request and response bytes and independently pinned wire
vectors. The lane then requires mutations to be killed at each claimed boundary:

- cycle/runtime: BUSY, SET value, RETIRE ID, ABORT discard, and length-order
  mutations must fail the adversarial testbench;
- model/RTL: JUMP payload-width and XOR deferred-decision mutations must fail
  byte-exact differential comparison;
- generated-artifact provenance: a one-byte mutation must change the pinned
  snapshot hash.

The JSON receipt records each command, exit status and mutation result. A
surviving mutation fails the lane. These checks demonstrate sensitivity only
to the named boundaries; they do not imply completeness.

## Residual gaps

- no full opcode exhaustive proof or liveness proof;
- no Lean-to-packet-RTL refinement;
- BLAKE3 service packets are model-only;
- no physical-cell full-profile netlist, place-and-route, FPGA byte log, or
  silicon evidence;
- bounded vectors do not cover the full 128-bit/state/packet space;
- the generated hierarchy snapshot has a provenance pin only; it has no
  synthesis, simulation-equivalence, or unbounded sequential-equivalence claim.

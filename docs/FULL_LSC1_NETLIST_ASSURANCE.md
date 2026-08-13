# Full LSC-1 synthesized-netlist assurance

This HOST-only, non-release lane extends—but does not replace—the bounded
FULL-A lane in `docs/LSC1_FULL_PROFILE_ASSURANCE.md`. FULL-A's elaborated
snapshot is provenance-only. This lane synthesizes the canonical
`lean_silicon_lsc1` packet-controller hierarchy into a flattened Yosys generic
netlist and compares every public output bit (`uo_out`, `uio_out`, and
`uio_oe`) with the authored RTL. It does not consume or make claims about the
separate LSC-1u physical/release netlists.

The reviewed plan pins the starting `main` commit/tree, complete RTL manifest,
top, clock/reset interpretation, observables, constraints, and the exact CI
OSS CAD Suite distribution. Each private-cache receipt additionally hashes
every actual RTL input and generated artifact and records the exact executable
version strings and commands.

```sh
cache="$(mktemp -d)"
chmod 700 "$cache"
LSC1_FULL_NETLIST_CACHE="$cache" make full-lsc1-netlist-assurance
python3 -m json.tool "$cache/receipt.json"
(cd "$cache" && sha256sum -c SHA256SUMS)
```

The correspondence harness asserts all 24 wrapper output bits. Reset is
asserted on an initialization edge preceding the first comparison; `ui_in`,
`uio_in`, `ena`, reset, abort, and transmit backpressure are arbitrary on and
after the first compared edge. Mandatory three-edge whole-design and controller
BMCs include the initialization reset edge, the first compared reset state,
and an operational state after an arbitrary post-reset transition. Longer
implemented-opcode sequences run directly on the synthesized netlist.
Transactional responses are compared byte-for-byte with the executable model;
valid NEGOTIATE is checked against an independent canonical-RTL wire vector
because model-only service feature bits are explicitly outside this lane.
Temporal induction is attempted under a 15-second HOST ceiling and its exact
pass or tool blocker is retained without weakening the bounded and trace
results. Separate controller
invariants cover reset/abort clearing, response stability under backpressure,
receive exclusion while computing/transmitting, event exclusivity, staged
transaction BUSY, and response arbitration. Existing adversarial simulations
witness every implemented opcode plus framing faults, reset, abort,
backpressure, staging, and RETIRE; the lane reruns them rather than duplicating
their vectors.

A deliberate observable-bit correspondence mutation must produce a formal
failure. Existing FULL-A behavioral/model mutations remain required by the
ordinary CI lane.

## Explicit limits

The netlist is generic digital synthesis output, not a physical cell netlist.
This lane generates no placement, routing, timing, power, GDS/OAS, FPGA,
silicon, SKY26c, or shuttle evidence. It does not bridge Lean to RTL and does
not implement the model-only BLAKE3 service exchange. Bounded correspondence
does not imply correctness against the protocol model; controller invariants
are safety properties, not fair-progress liveness.

## Unbounded boundary and decomposition evidence

True whole-design unbounded closure is not claimed. On the pinned 2026-08-09
HOST suite, extending the arbitrary-input reset-prefix miter from three to five
edges reached 15.9 GiB RSS at depth 5 after 3 minutes 15 seconds without a
result. A synthesis-aware matched-point decomposition held near 1.9 GiB and
proved thousands of state bits, but one direct-SAT receiver/controller state
point (`packet_core.addr_c[20]`) remained unresolved after more than 9 minutes.
The ordinary lane therefore keeps the mandatory depth-3 gate and records its
bounded temporal-induction attempt; neither resource outcome is converted into
a pass.

The semantic blocker is the monolithic packet frontend's very wide procedural
transition relation: result construction expands 543-bit response temporaries
across many opcode branches, while the receiver carries a 4096-bit payload
state. Current Yosys SAT decomposition does not provide a proved cut relation
connecting those internal points back into a reset-reachable whole-design
invariant. Treating matched names as axioms would be unsound, so this lane does
not do so. The existing separately proved arithmetic, stream, dereference,
jump, scalar-lifecycle, and arbitrary accepted-sequence results remain required
and unchanged; they do not silently upgrade the whole RTL/netlist claim.

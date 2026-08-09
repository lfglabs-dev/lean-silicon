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
after the first compared edge. A whole-design two-edge BMC
(reset plus an arbitrary post-reset transition) is mandatory. Longer
implemented-opcode sequences run directly on the synthesized netlist.
Transactional responses are compared byte-for-byte with the executable model;
valid NEGOTIATE is checked against an independent canonical-RTL wire vector
because model-only service feature bits are explicitly outside this lane.
Temporal induction is attempted under a 15-second
HOST ceiling and its exact pass or tool blocker is retained without weakening
the bounded and trace results. Separate controller
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

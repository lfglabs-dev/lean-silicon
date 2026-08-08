# Realistic leanVM-b / zkDSL workload validation

This is the dedicated issue #51 lane. It is non-release work and is explicitly
outside the SKY26c submission critical path: it is not called by `check`, does
not modify `src/`, `release/`, FPGA bitstreams, GDS, tags, or release gates.

## Reproduce

Check out the exact candidate head and the pinned upstream leanVM-b commit, then
use private mutable caches outside either checkout:

```sh
mkdir -p "$private/receipt" "$private/tmp"
chmod 700 "$private" "$private/receipt" "$private/tmp"
git clone https://github.com/leanEthereum/leanVM-b.git "$private/leanVM-b"
git -C "$private/leanVM-b" checkout --detach c308034ab78619b39a59d26f3dc60e7df5b52649
export CARGO_HOME="$private/cargo" RUSTUP_HOME="$private/rustup" TMPDIR="$private/tmp"
export PATH="$CARGO_HOME/bin:$PATH"
rustup toolchain install 1.88.0 --profile minimal
WORKLOAD_CACHE="$private/receipt" LEANVM_B_UPSTREAM="$private/leanVM-b" make workload-validation
python3 -m json.tool "$private/receipt/receipt.json"
```

The command rejects a dirty candidate or upstream checkout, an upstream SHA or
Cargo.lock mismatch, a non-private/in-tree receipt directory, changed source,
origin, or artifact hashes, changed elaboration counts, and outcomes that do
not reproduce the plan. For every workload it recompiles and executes the
pinned source through the public upstream `lean_compiler`/`Program::execute`
interfaces, requires the checked-in bytecode and final execution oracle to
match, then runs the leanSilicon host/model comparison. `workloads/plan.json`
pins all inputs, derivations, runtime values, expected successes and expected
failures. The per-workload JSON files and aggregate `receipt.json` are the
machine-readable receipts; they are mutable run evidence and are not committed
release artifacts.

## Selection and coverage

The three small programs are scaled, auditable instances of use cases present
at the pinned upstream source, not claims about a broad benchmark suite:

| Workload | Source ground | Included surface | Observed result |
| --- | --- | --- | --- |
| `field_division` | `lean_compiler/tests/field_div.rs` | compiler back-solving, SET/MUL/XOR/JUMP, final memory and cycles | full functional/model match: 16 slots, 9 executed cycles/steps |
| `heap_recurrence` | `rec_aggregation/src/fibonacci.rs` | HeapBuf, `mul_range`, pointer/DEREF-shaped recurrence | expected failure at pc 1 (`bad_pointer`): 64 slots, 1/58 steps reached |
| `blake3_stack` | `lean_compiler/tests/stack_buf.rs` | StackBuf and a realistic BLAKE3 service request | expected unsupported stop at pc 4: 16 slots, 4/10 steps reached |

The receipt is successful only when all three outcomes reproduce. A lane pass
therefore means one match plus two correctly detected limitations; it does not
turn failures into conformance. Opcode coverage for the matched workload is
SET_CONSTANT, MUL_NATIVE, XOR, and JUMP. The other sources demonstrate missing
HeapBuf pointer preparation and BLAKE3 service integration before those paths
can be credited as covered.

Large XMSS aggregation and recursive-proof workloads from the upstream README
are excluded: executing their prover/verification benchmarks would conflate VM
workload validation with proof-system and machine benchmarking, take substantial
resources, and cannot exercise unsupported BLAKE3 end to end here. The upstream
Fibonacci default is scaled down from 200,000 iterations because this lane asks
whether interfaces accept the workload shape, not for a throughput claim.
Witness-dependent, negative, and proof-generation tests are also excluded
because the public export adapter cannot set or inspect upstream private witness
and trace fields. These exclusions bound generality explicitly.

## Evidence classification and observations

- **Functional/model:** a live pinned Rust compiler/executor is the oracle for
  bytecode, cycles and final memory. The leanSilicon Python host/model matches
  only the field-division instance. Per-step upstream comparison is impossible
  because `Execution::trace` is private at the pinned revision.
- **RTL/FPGA:** no RTL simulation, synthesis, place-and-route, FPGA image, board
  exchange, timing, or resource-utilization evidence is produced by this lane.
  The repository's separate bounded RTL/FPGA evidence must not be attributed to
  these workloads.
- **ASIC:** none. Any future fabricated-silicon workload receipt must identify a
  die/board, bitstream or firmware, instruments, environment and raw exchanges;
  simulation/model output cannot predict silicon behavior.

The only performance/resource observations are deterministic counts: upstream
cycles, bytecode slots, memory prefix length, and model steps in the JSON
receipt. Wall-clock compiler/runtime timings and host memory consumption are
not recorded as benchmarks; no controlled machine, repetition/warm-up policy,
or resource instrumentation exists. No throughput, FPGA utilization, timing
closure, power, area, or silicon performance claim is made.

Residual limitations include the finite three-program sample, a fixed public
input `[1, 0]`, no public upstream per-step trace, no Lean-to-model/RTL proof,
the early HeapBuf pointer failure, absent BLAKE3 integration, and no RTL, FPGA,
physical-design, or ASIC execution. Promotion into any release or SKY26c gate
requires separate evidence and review.

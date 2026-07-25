# Proof-boundary correspondence matrix

LSC-1 is **not currently marketed as formally verified**.  The repository
contains useful proofs, bounded formal checks, simulations, and frozen-source
evidence, but they apply at different boundaries.  A check in one row does not
establish a correspondence to another row unless the bridge named below has
been completed.

| Layer | Current artifact and claim | What it does not establish | Required outgoing bridge and release gate |
|---|---|---|---|
| Frozen upstream semantics | The frozen `leanVM-b` source at `c308034ab78619b39a59d26f3dc60e7df5b52649`, documented in `docs/SEMANTICS.md`. | It is not an LSC-1 implementation or an LSC-1 theorem. | **Frozen-to-oracle traceability:** versioned opcode/fault mapping, locked-checkout vector regeneration, and official zkDSL validation gate. |
| Docs/reference oracle | `docs/semantics/reference/oracle.py` and its vectors are an executable scalar reference for selected frozen behavior. | The oracle is documentation/reference code, not a proof and not a full packet-controller model. | **Oracle-to-functional-model refinement:** reviewable operation/fault coverage table and Lean theorem for the v1 packet contract. |
| Lean functional models | `lean/` proves stated properties of simplified/executable models (including GF8 and scoped ISA, memory, address, and optimality models). | No current theorem connects these models to the full LSC-1 SystemVerilog controller or the full frozen ISA. `GF8.lean`'s `native_decide` result is **not** a proof of the production `GF(2^128)` multiplier. | **Functional-to-RTL correspondence:** a shared v1 state/packet relation, all-opcode refinement theorem, and a checked mapping from that relation to the exact LSC-1 RTL. |
| Authored SystemVerilog RTL | `asic_core/rtl/` is the authored hardware; `lean_silicon_lsc1` currently wraps the exercised MinCore seed. | It is seed-0, not the complete v1 packet executor, and source RTL alone is not a proof. | **RTL completion gate:** complete packet decoder/controller plus assertion inventory tied to the v1 relation and source manifest. |
| SBY properties over exact SV modules | `formal/gf8_mul.sby` checks the exact parameterized SV multiplier instantiated at 8 bits, with the stated finite bound. | It does not prove the full controller, arbitrary stream behavior, production GF(2^128) multiplication, or ISA correspondence. | **Controller-formal gate:** properties over the exact completed `lean_silicon_lsc1` modules, with assumptions, depths/induction, and coverage documented per property. |
| Simulation and differential evidence | Python/HDL tests and future packet differential tests compare executable artifacts on finite vectors/traces. | Passing vectors are evidence, not a universal theorem or a synthesis-equivalence proof. | **Differential gate:** generated frozen/oracle/Lean/RTL v1 vectors, fault and stall coverage, reproducible seeds, and zero mismatches. |
| Synthesis netlist and PPA | Yosys/OpenLane synthesis and Tiny Tapeout reports characterize a selected build. | A synthesized netlist/PPA report does not prove it preserves RTL behavior. | **RTL-to-netlist equivalence gate:** reproducible synthesis inputs plus sequential equivalence (including clock/reset constraints) for the release top, before PPA is treated as implementation evidence. |

## Current hard limits

- There is no theorem connecting the full LSC-1 SV controller to the full
  frozen leanVM-b ISA.
- There is no RTL-to-netlist equivalence result yet.
- The GF8 `native_decide`/bounded-SBY work is intentionally a small arithmetic
  boundary; it is not the production GF(2^128) multiplier proof.
- `Optimality.lean` proves only the stated arithmetic lower bounds under its
  declared channel/gate/state assumptions.  It makes no global circuit,
  technology-mapping, area, power, or timing optimality claim.

The project may use “formally verified” for LSC-1 only after the bridges above
are complete and their gates are recorded as passing for a fixed source,
protocol, toolchain, and synthesized release configuration.

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
| Lean v1 packet/transaction foundation | `Packet.lean` proves checksum-parametric request/response round trips and leading validation precedence; `Transaction.lean` proves staging atomicity, abort preservation, matching and mismatched retirement behavior, reset, and exactly-once retirement for the pure functional state model. | The checksum parameter is not yet instantiated by a CRC-32 correctness proof. Instruction execution is supplied as a proposed transition; there is no oracle, RTL, netlist, or full frozen-ISA refinement theorem. BLAKE3 service states are outside this slice. | **Instruction/refinement lanes:** connect arithmetic and DEREF/JUMP results to `Transition`, prove CRC-32 instantiation, extend service states, then define the Lean-to-RTL transition relation. |
| Lean byte-serialization model | `lean/LeanVMBMinCore/ByteSerialization.lean` proves, for all `BitVec 128` values, that the little-endian 16-beat shift-in/shift-out model places byte `i` in lane `i` and that `deserialize ∘ serialize` and `serialize ∘ deserialize` are identities. All theorems are kernel-checked with no `native_decide` and no SAT-generated axioms (`#print axioms` shows only `propext`, `Quot.sound`). | It is a proof about the Lean model of byte ordering only. There is no mechanized theorem linking it to `gf2n_mul_bitstream.sv`; the RTL side of the same ordering property is established separately and independently by `formal/gf128_serialize.sby`. It says nothing about GF(2^128) multiplication. | **Model-to-RTL serialization bridge:** a checked correspondence between this Lean shift model and the RTL shift registers, so the two ordering results become one argument instead of two agreeing ones. |
| Authored SystemVerilog RTL | `asic_core/rtl/` contains the packet decoder/controller, two-phase retirement and scalar SET/XOR/MUL/DEREF/JUMP execution around the exercised MinCore datapath. | BLAKE3 service exchange is not implemented, and source RTL alone is not a proof. | **RTL completion gate:** complete the service path plus an assertion inventory tied to the v1 relation and source manifest. |
| SBY properties over exact SV modules | `formal/gf8_mul.sby` checks the exact parameterized SV multiplier instantiated at 8 bits, with the stated finite bound. | It does not prove the full controller, arbitrary stream behavior, production GF(2^128) multiplication, or ISA correspondence. | **Controller-formal gate:** properties over the exact completed `lean_silicon_lsc1` modules, with assumptions, depths/induction, and coverage documented per property. |
| SBY byte-ordering property at WIDTH=128 | `formal/gf128_serialize.sby` proves by k-induction, over a symbolic `(* anyconst *)` 128-bit operand, that the shipped `gf128_mul_bitstream` loads byte `i` of the operand on load beat `i` and emits byte `j` on result-shift beat `j`. Reachability of the final shift beat is covered. | It proves **ordering only**, under a fixed schedule with `abort = 0`, one identity multiplier bit, and no back-to-back or partial transactions. It is **not** a proof that the GF(2^128) product is correct, and not a controller or ISA result. | **GF(2^128) product gate:** an operand-symbolic proof that the accumulator after 128 multiplier bits equals carry-less product mod `x^128 + x^7 + x^2 + x + 1`, plus a stream-protocol property covering abort and back-to-back transactions. |
| SBY handshake property on shipped controller RTL | `formal/stream_alu_mul_pulse.sby` binds a checker into the shipped `leanvm_b_stream_alu` and proves by k-induction that `mul_a_valid`, `mul_bit_valid`, and `mul_result_shift` are mutually exclusive in every reachable state, with free stream inputs. Each of the three pulses is separately covered as reachable. This is the first assertion to hold over shipped controller RTL rather than a standalone harness. | It checks one documented handshake precondition of `gf2n_mul_bitstream`. It does **not** establish opcode decode correctness, result values, stream framing, abort handling, or any part of the packet controller. | **Assertion-inventory gate:** the remaining documented preconditions and framing invariants of the shipped modules, bound and proved the same way, and tied to the v1 relation. |
| Simulation and differential evidence | Python/HDL tests compare scalar packet responses byte-for-byte on deterministic success and fault vectors. | Passing vectors are evidence, not a universal theorem or a synthesis-equivalence proof. | **Differential gate:** extend generated frozen/oracle/Lean/RTL v1 vectors through services, fault and stall coverage, reproducible seeds, and zero mismatches. |
| Synthesis netlist and PPA | Yosys/OpenLane synthesis and Tiny Tapeout reports characterize a selected build. | A synthesized netlist/PPA report does not prove it preserves RTL behavior. | **RTL-to-netlist equivalence gate:** reproducible synthesis inputs plus sequential equivalence (including clock/reset constraints) for the release top, before PPA is treated as implementation evidence. |

## Current hard limits

- There is no theorem connecting the full LSC-1 SV controller to the full
  frozen leanVM-b ISA.
- There is no RTL-to-netlist equivalence result yet.
- The GF8 `native_decide`/bounded-SBY work is intentionally a small arithmetic
  boundary; it is not the production GF(2^128) multiplier proof.
- The WIDTH=128 serialization results (`formal/gf128_serialize.sby` and
  `lean/LeanVMBMinCore/ByteSerialization.lean`) prove **byte ordering**, not
  GF(2^128) multiplication.  The production multiplier's arithmetic remains
  unproved at 128 bits.
- The Lean and SBY serialization results are two independent arguments about
  the same intended ordering.  No mechanized refinement connects them; agreement
  between them is corroboration, not a single proof.
- `formal/stream_alu_mul_pulse.sby` is the only property that holds over shipped
  controller RTL, and it covers exactly one handshake precondition.  The rest of
  `asic_core/rtl/` still carries no assertions.
- The `stream_alu_mul_pulse` config depends on the `yosys-slang` plugin.  The
  built-in Yosys frontend silently drops `bind` instances, which would turn the
  run into a vacuous pass; reproduce it only with `read_slang`.
- `Optimality.lean` proves only the stated arithmetic lower bounds under its
  declared channel/gate/state assumptions.  It makes no global circuit,
  technology-mapping, area, power, or timing optimality claim.

The project may use “formally verified” for LSC-1 only after the bridges above
are complete and their gates are recorded as passing for a fixed source,
protocol, toolchain, and synthesized release configuration.

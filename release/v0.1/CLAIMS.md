# v0.1 evidence and claim boundary

| Claim level | v0.1 status | Scope |
|---|---|---|
| Implemented | yes | LSC-1u fixed-width XOR, MUL, and SET micro-ops and Tiny Tapeout wrapper |
| Simulated RTL | yes | Cocotb protocol, reset, enable, backpressure, XOR, MUL, and SET tests |
| Proved formal bounded | yes | documented LSC-1u protocol, reachability, XOR refinement, GF(2^128) stream refinement, and compositional operation properties within their stated assumptions/bounds |
| Simulated gate-level | yes | exact-main hardened netlist passed the Tiny Tapeout Cocotb gate-level lane |
| Hardened | yes | `sky130A` GDS/OAS produced; GDS and precheck jobs passed |
| Silicon-validated | no | no fabricated device has been tested |

These statements apply to the reduced **LSC-1u (LSC-1 Micro)** Tiny Tapeout
sub-core. They do not establish equivalent claims for the full **LSC-1**
packet executor.

## Explicit non-claims

- No full-release RTL-to-netlist or sequential equivalence result is claimed.
- No ASIC-readiness or shuttle-acceptance claim is made; the bundle is a
  candidate for further pre-submission verification.
- No silicon proof or physical-hardware validation is claimed.
- The bounded, layer-specific formal results are not a proof that the full
  release or the full LSC-1 design is formally verified.

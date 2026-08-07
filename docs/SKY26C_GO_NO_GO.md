# SKY26c submission go/no-go dossier

**Decision: NO-GO for submission as of 2026-08-07.** The selected, immutable
v0.1.1 physical-flow payload has successful GDS, precheck, and gate-level jobs,
and its hash-pinned service-produced archive is retained in this repository.
Submission, payment, shuttle acceptance, FPGA hardware validation, and silicon
validation have not occurred. A GO requires the pre-submit steps below and a
separately authorized submission decision; this dossier does not authorize one.

This is a documentation assessment of `main` at merge commit
`f10be11b05a4e798a962e13c61de2eff8cd5ddec`. It preserves the artifact and claim
boundaries of the merged v0.1.1 package and does not modify v0.1.

## Immutable candidate identity

The selected candidate is the exact-main Tiny Tapeout physical workflow run
[31203929606](https://github.com/lfglabs-dev/lean-silicon/actions/runs/31203929606),
whose successful jobs are GDS `92950273839`, precheck `92951964559`,
gate-level test `92951964637`, and viewer `92951964648`. The run head is source
commit `741a2073e0d341a15bb130b1d75295bbceb138df`, tree
`6d0085cb016c7ce317ab91160c670b44d6fb51fd`, the source identity pinned by
`release/v0.1.1/MANIFEST.json`. It used `sky130A`, open_pdks
`8afc8346a57fe1ab7934ba5a6056ea8b43078e71`, and LibreLane 3.0.3.

The service-produced `tt_submission` ZIP is GitHub artifact ID `9004116698`,
named `tt_submission`, with locally reproduced archive SHA-256
`1c6721712d3dec19f0b143bd3af99e5e0982928a151d6142a25f5bf0dd1ef80f`.
The archive is the submission-container identity; payload hashes identify the
files independently of ZIP metadata:

| Selected payload | SHA-256 |
| --- | --- |
| `artifacts/tt_um_lfglabs_lsc1u.gds` | `52a10ef119b3cf435ad13041203f9b6200902df10f82b1e00890193abb2cc307` |
| `artifacts/tt_um_lfglabs_lsc1u.oas` | `a76516d3f84ade685a4b164908aaa57ab65ee5863914f10721c8b0fcde73093c` |
| `artifacts/tt_um_lfglabs_lsc1u.v` | `97000459a97f1d775db06ed88fefb59e28fde09b27a5046aaadd036ad01e16bc` |

The exact service-produced archive is retained at
`release/v0.1.1/evidence/tt_submission-9004116698.zip`; CI verifies its archive
hash and the selected netlist hash before every bounded-equivalence run.

## Actual Tiny Tapeout pinout

The following is the implemented top-level mapping in `info.yaml`,
`src/tt_um_lfglabs_lsc1u.sv`, and `docs/LSC1U_ARCHITECTURE.md`, not a proposed
package-pin map. `clk`, active-low `rst_n`, and `ena` are standard Tiny Tapeout
control pins.

| Pins | Direction | Function |
| --- | --- | --- |
| `ui_in[7:0]` | input | `REQUEST_BYTE[7:0]` / RX byte data |
| `uo_out[7:0]` | output | `RESPONSE_BYTE[7:0]` / TX byte data |
| `uio[0]` | input | `RX_VALID` |
| `uio[1]` | output | `RX_READY` |
| `uio[2]` | output | `TX_VALID` |
| `uio[3]` | input | `TX_READY` |
| `uio[4]` | output | `BUSY` |
| `uio[5]` | output | `FAULT` |
| `uio[6]` | reserved input | ignored |
| `uio[7]` | output | one-cycle `DONE_PULSE` |

The design is a 1×2 digital tile with a declared 25 MHz ASIC clock. Its
interface carries fixed-width LSC-1u micro-operations (SET, XOR, and GF(2^128)
MUL); it is not the full LSC-1 packet interface.

## Evidence and exact boundaries

| Layer | Evidence | What it does and does not establish |
| --- | --- | --- |
| Precheck | Run `31203929606`, job `92951964559`, success; `precheck_reports` artifact ID `9004196423`, archive SHA-256 `f0d72e5a31826d03991dfac19273086c989b5c8ab24e06619b56f9f6ca17c3e9`; payload `results.xml` SHA-256 `d01553d955714a00e42d47b60700cc01e15e15b8b3ea1777b658603d4b3ad42d` and `magic_drc.txt` SHA-256 `82a56bff28dab01bc0fd8c64b3c2debaf8d4ca0769e6c30a812a4a76badd6f7c`. | Tiny Tapeout flow checks passed for the selected payload. This is not shuttle acceptance, manufacturability, timing, power, analog, or silicon evidence. |
| Gate level | Run `31203929606`, job `92951964637`, success; `gatelevel_test_results` artifact ID `9004146486`, archive SHA-256 `55c7bc93ce17407095f73e15de8f1bb3f5c2c38c2c048c3a2978d9851a7ebe30`; JUnit payload SHA-256 `a01c222fe71d091622a2dfda4e823fbe323826a1587d0eb530e68facb8cf6aa2`. | Simulation of the hardened netlist in the Tiny Tapeout lane. It is not exhaustive, physical FPGA execution, or fabricated-silicon behavior. |
| Formal and CI | Exact-head CI run [31203930126](https://github.com/lfglabs-dev/lean-silicon/actions/runs/31203930126), head `741a2073e0d341a15bb130b1d75295bbceb138df`, success. This PR adds a fail-closed lane for artifact `9004116698` and its selected netlist hash, with exhaustive sequential equivalence through 74 rising edges, an explicit reset-release/output SAT witness, and a required failing mutation. | The initial rising edge constrains reset asserted; all later inputs are arbitrary. The result is bounded, does not span a complete 128-bit multiply, and covers two-state digital equivalence at the 24 observable outputs—not unbounded equivalence, timing/physical equivalence, or Lean-to-RTL correspondence. See `docs/LSC1U_RELEASE_EQUIVALENCE.md`. |
| FPGA | The checked-in Tiny Tapeout ASIC-simulator build at `results/tt-fpga-asic-simulator-20260801/` routed for ICE40UP5K at 12 MHz and reported 46.46 MHz maximum. Harness/unit evidence is software-only. | This is build evidence only. No bitstream was executed for the v0.1.1 package, no ULX3S board was attached or driven, and no FPGA datapath was physically validated. The earlier unauditable ULX3S-run claim was retracted and is not inherited. |

GDS/precheck, gate-level simulation, rendering, formal checks, and FPGA-image
building are pre-silicon evidence. None implies correct fabricated silicon.

## FPGA versus ASIC

- The ASIC candidate targets sky130A standard cells in a 1×2 tile and declares
  25 MHz. The ASIC-simulator image maps the same LSC-1u top into ICE40UP5K LUTs,
  flip-flops, and FPGA I/O, uses a 12 MHz constraint, and is not the GDS/OAS.
- FPGA routing/timing uses FPGA primitives and interconnect, so it provides no
  ASIC timing, power, clock-tree, physical-rule, or analog evidence. Conversely,
  ASIC precheck does not show that a board, UART bridge, loader, or host path
  works.
- The separate ULX3S harness targets full LSC-1/debug integration and has a
  partly hypothetical v3.1.8 LPF pin subset. It is outside the Tiny Tapeout
  `info.yaml` source list and outside this submission artifact.

## Residual risks and unknowns

- The checked-in archive and selected payload identities must be reconfirmed
  immediately before submission and matched to the live portal selection.
- The selected physical netlist has exhaustive two-state equivalence to its
  pinned RTL at the 24 observable outputs through 74 rising edges. It lacks
  unbounded equivalence, and the bound does not span a complete 128-bit
  multiply.
- No independent review of the live submission form, selected revision, PDK,
  tile count, rendered layout, reports, or invoice has been recorded.
- There is no physical FPGA or silicon validation, no full LSC-1 proof, and no
  complete Lean-to-RTL bridge. The retained profile intentionally omits packet
  framing/CRC, memory/fetch, DEREF/JUMP, BLAKE3, witnesses, and commit tracking.
- A successful automated flow does not resolve timing/power/analog/fabrication
  behavior or guarantee Tiny Tapeout acceptance. Fabricated-chip performance
  and the production/package schedule remain unknown until post-silicon test.

## Bring-up plan if separately fabricated

1. Before power, record board/chip identifiers, inspect assembly and rails, set
   current limiting, and confirm the Tiny Tapeout board's specified supply and
   clock configuration. Do not infer pin behavior from the FPGA harness.
2. At a conservative clock, assert `rst_n=0`, select with `ena`, and verify idle
   outputs: no transfer, busy, fault, or done indication. Exercise deselect and
   reset abort behavior before arithmetic.
3. Check ready/valid backpressure and stable TX data using SET with zero, walking
   ones, and fixed patterns; verify exactly one `DONE_PULSE` after the final
   accepted byte. Then verify XOR and unsupported-opcode `0xe0`/`FAULT` behavior.
4. Run GF(2^128) MUL zero/one/basis and frozen differential vectors, comparing
   every byte with the checked-in model. Sweep clock downward/upward and repeat
   across available voltage/temperature points without exceeding board or
   shuttle specifications.
5. Preserve raw captures, firmware/tool versions, board/chip IDs, conditions,
   and vector hashes. Only after review may results be described as validation
   of the tested samples and conditions, never of untested silicon generally.

## Live SKY26c schedule and price

Accessed **2026-08-07**. Tiny Tapeout's authoritative
[chips schedule](https://tinytapeout.com/chips/) lists **TTSKY26c open** with a
**2026-09-07 submission deadline** (shuttle CI-2609). The project declares a
1×2 digital tile. Tiny Tapeout's live [sky130A pricing
page](https://tinytapeout.com/specs/analog/) states **€70 per tile**, so its
published silicon-area price is **€140** for 1×2. That page explicitly excludes
the ASIC, PCB, and shipping; taxes, delivery, optional hardware, eligibility,
early-bird availability, and checkout total are not established here. Tiny
Tapeout directs buyers to its live [calculator](https://app.tinytapeout.com/)
for the current transaction price. No order, payment, or submission was made.

## Conditions to change NO-GO to GO

1. Verify the checked-in artifact `9004116698` archive SHA-256 and the GDS, OAS,
   and netlist payload hashes above, and preserve the verification receipt.
2. Inspect the selected reports/render and the submission portal together;
   confirm SKY26c, sky130A, 1×2, the exact repository/revision/artifact, deadline,
   current quote, and all terms without changing the candidate bytes.
3. Obtain an independent sign-off that explicitly accepts the formal gap, lack
   of hardware validation, omitted full-LSC-1 functions, and other residual
   risks. Any changed source or physical payload is a new candidate requiring
   new GDS, precheck, gate-level, checksums, and dossier review.
4. Receive separate authorization to submit and pay. This repository decision
   record alone is not that authorization.

# LSC-1u v0.1.1 fabrication-readiness record

**Decision: NO-GO.** This record strengthens review of the already selected
pre-silicon payload. It is not a foundry signoff, shuttle acceptance, hardware
validation, submission authorization, invoice, order, or claim about fabricated
silicon. The canonical machine-readable identity is
`FABRICATION_MANIFEST.json`; verify it with:

```sh
python3 tools/verify_fabrication_bundle.py
```

The candidate is physical-flow run `31203929606` at source commit
`741a2073e0d341a15bb130b1d75295bbceb138df` and tree
`6d0085cb016c7ce317ab91160c670b44d6fb51fd`. Its retained submission archive
is GitHub artifact `9004116698`, SHA-256
`1c6721712d3dec19f0b143bd3af99e5e0982928a151d6142a25f5bf0dd1ef80f`.
The repository has advanced since that source commit; later source changes do
not silently become part of this physical payload.

## Proof and evidence matrix

| Question | Payload-tied receipt | Result and boundary |
| --- | --- | --- |
| Source identity | Commit/tree above; validator asks Git for the commit's actual tree | Exact object identity passes. This does not say current HEAD was fabricated. |
| GDS/OAS/netlist/LEF | Hashes and minimum sizes in the canonical manifest; bytes in retained archive | Present and hash-valid. No foundry or shuttle acceptance is inferred. |
| DEF | Exact-run `GDS_logs` artifact `9004115188`, archive hash and final DEF hash in manifest | Identified, but the DEF byte is not retained in Git or the submission ZIP. Re-download is required for byte verification. |
| Pinout/config/PDK/toolchain | `info.yaml`, four config members, `pdk.json`, and pinned versions in manifest | Hash-valid and nonempty; validator also requires implemented pin endpoints and 25 MHz declaration. |
| Precheck/DRC | Physical job `92951964559`; 15-case normalized receipt; archive metrics require `magic__drc_error__count=0` | CPU flow evidence for this payload, not independent foundry DRC. |
| LVS | Exact archive metrics require `design__lvs_error__count=0`; full Netgen report remains in `GDS_logs` | Flow LVS passed; extracted transistor-level behavior and analog effects are outside the claim. |
| Antenna | Exact archive metrics require zero violating nets, pins, and route antenna count | Flow antenna check passed; fabrication outcome is unknown. |
| Gate-level behavior | Physical job `92951964637`; five named, non-vacuous JUnit cases; source receipt hash retained in manifest | Selected hardened netlist simulation passed. It is not exhaustive or post-silicon evidence. |
| RTL/netlist equivalence | `docs/LSC1U_RELEASE_EQUIVALENCE.md` and merged PR #56 | Unbounded sequential equivalence for the selected v0.1.1 netlist under documented two-state/reset assumptions; not timing, analog, or Lean-to-RTL equivalence. |
| Timing | Archive metrics require zero setup and hold violation counts; PDK/flow/corners are payload-pinned | Static timing flow evidence only. Clock/power/variation models and fabrication remain residual risks. |
| Density | `design__instance__utilization=0.600044` required by validator | Exact reported utilization, not a yield or manufacturability guarantee. |
| Non-vacuity/mutation | Validator enforces sizes, required classes, 20 test cases, and zero counters; test suite corrupts the GDS hash and requires failure | Local fail-closed behavior demonstrated. It does not mutate or rerun proprietary/foundry signoff. |

The precheck and gate-level XML files are normalized, review-sized projections
of the service-produced JUnit payloads. Their original payload hashes remain in
the manifest, so the projections cannot be mistaken for byte-identical source
artifacts.

## Residual-risk register

| ID | Open risk | Required disposition before GO |
| --- | --- | --- |
| R1 | **DGX-paused ULX3S validation is unperformed.** The ULX3S is attached to the paused DGX/Spark lane and was deliberately not probed, configured, or driven. There is no current-release board execution receipt. | Perform only after separate authorization and when a non-Spark hardware path is available, or explicitly accept the absence. Never treat historical or simulator results as this validation. |
| R2 | Final DEF and full DRC/LVS/antenna logs are identified in service artifact `9004115188` but are not durably retained in Git. GitHub artifact retention can expire. | Re-download, verify the recorded archive and DEF hashes, inspect full reports, and preserve an approved durable copy if policy permits. |
| R3 | Automated open-source flow checks are not independent foundry signoff and cannot establish yield, power integrity, analog behavior, packaging, or working silicon. | Obtain the shuttle's required review/acceptance and record only its actual scope. |
| R4 | No fabricated device exists in this evidence set; bring-up behavior and achievable frequency are unknown. | Execute the bring-up checklist on identified samples and retain raw captures. |
| R5 | The source repository has moved beyond the candidate commit. | Reject any portal selection whose source revision or payload hashes differ; a change requires a new physical run and dossier. |
| R6 | Live price, tax, shipping, hardware, eligibility, and checkout total can change. | Recheck the live portal and record a quote before seeking payment authorization. |

## Submission checklist (no submission or payment authorized)

- [ ] Run the validator from a clean clone and retain stdout, HEAD, and Python version.
- [ ] Re-download artifacts `9004116698` and `9004115188`; verify both archive hashes and the external DEF hash.
- [ ] Independently inspect the GDS render, complete precheck, Magic/KLayout DRC, Netgen LVS, antenna, STA, and density reports.
- [ ] Confirm portal project, top `tt_um_lfglabs_lsc1u`, SKY130A PDK, 1x2 tiles, 25 MHz declaration, pinout, repository, candidate revision, and payload hashes.
- [ ] Confirm the live shuttle remains TTSKY26c and record its deadline, terms, availability, quote, tax, shipping, PCB/ASIC options, and total.
- [ ] Record explicit acceptance or mitigation of every residual risk, including R1.
- [ ] Obtain independent technical signoff and separate authority to submit and pay.
- [ ] After any authorized submission, record immutable portal/submission receipts without claiming acceptance until it actually occurs.

## Silicon bring-up checklist (only if separately fabricated)

- [ ] Record die/board/package IDs, board revision, photos, operator, time, firmware/tool versions, and hashes of all vectors.
- [ ] Inspect assembly; confirm documented rails and clock; set conservative current limits before power.
- [ ] With `ena=0` and reset asserted, verify safe idle/current behavior; then test reset release and reset during every controller state.
- [ ] At a conservative clock, test SET zero/walking-one/fixed patterns, ready/valid backpressure, stable response bytes, and exactly one `DONE_PULSE`.
- [ ] Test XOR, unsupported opcode/fault behavior, and GF(2^128) multiply zero/one/basis/frozen differential vectors byte-for-byte.
- [ ] Sweep clock only within board/shuttle specifications; if equipment permits, repeat across documented voltage/temperature points.
- [ ] Preserve raw logic-analyzer captures, current measurements, commands, failures, and environmental conditions. Scope conclusions only to tested samples and conditions.

## Dated schedule and cost evidence

Checked **2026-08-07**: Tiny Tapeout's
[chips schedule](https://tinytapeout.com/chips/) listed TTSKY26c open with a
**2026-09-07** submission deadline (CI-2609). Its
[SKY130 pricing page](https://tinytapeout.com/specs/analog/) listed **EUR 70 per
tile**, implying **EUR 140** of published tile-area pricing for the declared
1x2 design. The page excludes ASIC, PCB, and shipping; tax, delivery, optional
hardware, availability, eligibility, discounts, and checkout total are not
established. Recheck both sources and the live calculator before any decision.
No order, payment, or submission was made.

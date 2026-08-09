# v0.1.1 final-main release package

The payload-specific fabrication manifest, fail-closed verification command,
proof matrix, residual risks, and operational checklists are in
`FABRICATION_MANIFEST.json` and `FABRICATION_READINESS.md`. These additions do
not change the selected physical payload or this package's NO-GO boundary.

This bounded package describes final `main` after merged PR #45. It prepares a
new immutable version; it does not create, publish, move, overwrite, or delete
any tag or GitHub release. The existing `v0.1` objects remain historical and
immutable.

## v0.1 audit

- Annotated tag object `b214d961f70c0693bf19a148814756126d818399`
  dereferences to commit `14068d4a82803bc7e17f1219c29f4748bd257db7`
  and tree `e6c45d52125a7412b07428565c3243c676bea1a1`.
- The published v0.1 release targets that commit, but its checked-in
  `release/v0.1/MANIFEST.json` and reproducibility record pin the earlier
  commit `6f45fd663792f1329036829c1670cefd78d66630` and tree
  `1ffca601b105272bdbda5edb51a6c076dc4c328b`.
- The preserved `release/v0.1-candidate` branch is
  `b2f3f681fc1808a247e7f5d5de73f525dbc4c870`; it is not final main.
- PR #45 retracts the unauditable ULX3S physical-run claim. This package does
  not inherit that claim.

## Included boundary and receipts

`MANIFEST.json` pins final main's exact commit/tree, toolchains, frozen oracle,
exact-head CI, physical-flow jobs, GitHub artifact archive hashes, and selected
payload hashes. `SHA256SUMS.txt` covers the canonical package documents and the
durable copy of the selected service-produced archive.

The exact-main GDS run `31203929606` completed successfully. Its GDS, precheck,
gate-level test, and viewer jobs are identified in the manifest. The downloaded
artifacts record `sky130A`, `open_pdks` commit
`8afc8346a57fe1ab7934ba5a6056ea8b43078e71`, and LibreLane `3.0.3`; their
archive and selected payload checksums were reproduced locally.

The exact-main Tiny Tapeout RTL run `31203929947` completed successfully. The
exact-main CI run `31203930126` is the authoritative executable-model,
SystemVerilog, Lean, formal/lint, mutation, and synthesis receipt for the
checked-in source and harnesses. Its `formal/lsc1u_netlist_eq.sby` harness
compares RTL with the historical `release/v0.1` netlist (SHA-256
`0c85d1afefddf1166e4b3047500f9c27a03ad7198c9c075f505c4536888c03c3`), not
the selected exact-main physical-run netlist (SHA-256
`97000459a97f1d775db06ed88fefb59e28fde09b27a5046aaadd036ad01e16bc`).
The manifest records the historical boundary explicitly. The later
`make release-netlist-equivalence` lane fetches and hash-checks the selected
physical payload and provides the bounded 74-edge result described in
`docs/LSC1U_RELEASE_EQUIVALENCE.md`; it does not establish unbounded equivalence.

## Explicit limitations

- These results apply to the reduced LSC-1u Tiny Tapeout profile where stated,
  not to full LSC-1 end-to-end behavior.
- Formal results retain each harness's assumptions and bounds. The historical
  v0.1 netlist comparison is bounded, not unbounded sequential equivalence, and
  does not cover the selected v0.1.1 physical payload.
- There is no completed Lean-to-RTL correspondence proof for the full design.
- GDS/precheck, gate-level simulation, and rendering are physical-design-flow
  evidence; they do not prove timing, power, analog behavior, manufacturability,
  shuttle acceptance, or correct fabricated silicon.
- No ULX3S board run is claimed. No FPGA hardware or fabricated ASIC was
  attached or physically validated for this package.
- GitHub artifact archives are service-produced ZIPs; payload hashes identify
  the release bytes independently of ZIP container metadata. The selected
  `tt_submission` archive is retained verbatim under `evidence/` so the
  historical proof does not depend on service retention.
- No tag, GitHub release, submission, publication, merge, or branch deletion is
  part of this preparation PR.

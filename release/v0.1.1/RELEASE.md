# v0.1.1 final-main release package

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
payload hashes. `SHA256SUMS.txt` covers the two canonical package documents.

The exact-main GDS run `31203929606` completed successfully. Its GDS, precheck,
gate-level test, and viewer jobs are identified in the manifest. The downloaded
artifacts record `sky130A`, `open_pdks` commit
`8afc8346a57fe1ab7934ba5a6056ea8b43078e71`, and LibreLane `3.0.3`; their
archive and selected payload checksums were reproduced locally.

The exact-main Tiny Tapeout RTL run `31203929947` completed successfully. The
exact-main CI run `31203930126` is the authoritative executable-model,
SystemVerilog, Lean, formal/lint, mutation, and synthesis boundary.

## Explicit limitations

- These results apply to the reduced LSC-1u Tiny Tapeout profile where stated,
  not to full LSC-1 end-to-end behavior.
- Formal results retain each harness's assumptions and bounds. The fixed
  release netlist comparison is bounded, not unbounded sequential equivalence.
- There is no completed Lean-to-RTL correspondence proof for the full design.
- GDS/precheck, gate-level simulation, and rendering are physical-design-flow
  evidence; they do not prove timing, power, analog behavior, manufacturability,
  shuttle acceptance, or correct fabricated silicon.
- No ULX3S board run is claimed. No FPGA hardware or fabricated ASIC was
  attached or physically validated for this package.
- GitHub artifact archives are service-produced ZIPs; payload hashes identify
  the release bytes independently of ZIP container metadata.
- The package contains receipts and hashes, not duplicated large binary
  artifacts. Reproduction requires downloading the retained artifacts from the
  pinned run.
- No tag, GitHub release, submission, publication, merge, or branch deletion is
  part of this preparation PR.

# Tiny Tapeout ttsky26c: LSC-1µ

> **LSC-1µ (LSC-1 Micro) is a reduced Tiny Tapeout profile/sub-core of
> LSC-1—not “LSC-1/2”, LSC-2, or a second-generation architecture.** ASCII
> filenames, modules, identifiers, and URLs use `LSC-1u` / `lsc1u`.

The normative retained/excluded boundary and pin protocol are in
[LSC1U_ARCHITECTURE.md](LSC1U_ARCHITECTURE.md). Full LSC-1 in `asic_core/`
remains unchanged for FPGA and future larger ASIC targets. Tiny Tapeout builds
the thin `tt_um_lfglabs_lsc1u` top and profile-specific `lsc1u_core`.

## Evidence-driven reduction

The previous full-LSC-1 canary at commit
`ba954bcd0e6dbf101eba119d3234a80b12d9113e` used the maximum 8×4 macro. Yosys
mapped 32,551 cells with total standard-cell area 367,825.2736 µm², including
5,474 flops occupying 116,434.1696 µm². LibreLane then stopped with
`[DPL-0036] Detailed placement failed`; precheck and gate-level test were
skipped. That is a physical failure, not merely an RTL estimate.

The initial LSC-1µ 1×1 candidate synthesizes with local Yosys 0.33 to 1,433
generic cells and 283 flops. Hierarchical counts attribute 1,027 cells and 256
flops to the serial multiplier; the wrapper plus protocol/SET/XOR control uses
406 cells and 27 flops. These generic counts guide the experiment but are not
Sky130 area or routeability claims. The pinned ttsky26c GDS run is authoritative.
If MUL prevents routing, the next candidate removes that measured block while
leaving SET/XOR semantics intact.

## Flow and claim boundary

The workflow pins `TinyTapeout/tt-gds-action` to
`30d38a7dfc6fda561d452b196fc822af0332ec23`. Local RTL simulation, oracle
differential tests, lint, synthesis, and formal checks do not establish a
tapeout result. A physical success claim requires the real `gds`, `precheck`,
and `gl_test` jobs to pass and their area, utilization, timing, and routing
reports to be inspected.

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

The initial LSC-1µ 1×1 candidate synthesized in the real ttsky26c flow to
1,616 mapped Sky130 cells and 17,583.1136 µm², including 283 flops occupying
6,019.5232 µm². Its 16,493.3 µm² core area was too small: floorplan instance
utilization was 106.607%, and global placement reported 128.237% after its
pin-density adjustment (`GPL-0301`). Precheck and gate-level test were skipped.

The preceding local hierarchy synthesized to 1,433 generic cells. It attributed
1,027 cells and 256 flops to the serial multiplier; the wrapper plus
protocol/SET/XOR control used 406 cells and 27 flops. Since the mapped 1×1
design is only 28.237 percentage points over the global-placement limit, 1×2 is
the smallest evidence-based follow-up. MUL remains for that attempt. If 1×2
still cannot route, the next candidate removes the measured multiplier block
while leaving SET/XOR semantics intact.

## Flow and claim boundary

The workflow pins `TinyTapeout/tt-gds-action` to
`30d38a7dfc6fda561d452b196fc822af0332ec23`. Local RTL simulation, oracle
differential tests, lint, synthesis, and formal checks do not establish a
tapeout result. A physical success claim requires the real `gds`, `precheck`,
and `gl_test` jobs to pass and their area, utilization, timing, and routing
reports to be inspected.

# Tiny Tapeout integration checklist

1. Fork or copy the official Sky130 Verilog template.
2. Copy `src/*.sv`, `src/user_config.tcl`, and `info.yaml` into the template.
3. Rename `tt_um_leanvm_b_mincore` to a globally unique top-module name that
   includes the submitter's GitHub username; update `info.yaml` and the testbench.
4. Start with `tiles: 2x2`. Also run an exploratory `1x2` build; keep it only if
   placement, routing, and timing all pass with margin.
5. Run the official precheck and OpenLane/GitHub Actions flow.
6. Keep the target clock at 25 MHz until timing reports justify changing it.
7. Test the gate-level netlist with the same transactions in `test/tb_stream_alu.sv`.
8. Connect the physical board to an RP2040 PIO or FPGA ready/valid bridge.

## Host electrical/protocol behavior

- Host output: `ui_in[7:0]`, `RX_VALID`, `TX_READY`, `ABORT`.
- Host input: `uo_out[7:0]`, `RX_READY`, `TX_VALID`, `BUSY`, `FAULT`, `DONE`.
- Keep valid and data stable until ready.
- Never derive `RX_VALID` combinationally from `RX_READY`; XOR/SET use a
  combinational ready/valid path through the two interfaces.
- A PIO/FPGA bridge should register board-level signals if cable length or clock
  skew makes the direct path unreliable.

## Area decision rule

```text
1x2 passes with timing/routing margin: use 1x2
1x2 fails but 2x2 passes: use 2x2
2x2 fails: inspect mapped-cell hot spots before buying 3x2
```

The 273 source-level bits are compatible with an aggressive two-tile attempt,
but only the physical flow can answer whether the multiplier transition and
routing fit beside them.

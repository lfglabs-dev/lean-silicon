`default_nettype none
/* Pin-level contract for a future ULX3S harness; deliberately no wide bypass. */
module lean_silicon_lsc1_pins (
  input wire clk, input wire rst_n,
  output wire [7:0] asic_ui_in, input wire [7:0] asic_uo_out,
  output wire [7:0] asic_uio_drive, input wire [7:0] asic_uio_sample,
  output wire [7:0] asic_uio_oe
);
  assign asic_ui_in = 8'b0;
  assign asic_uio_drive = 8'b0;
  assign asic_uio_oe = 8'b0;
  wire _unused = &{clk, rst_n, asic_uo_out, asic_uio_sample};
endmodule
`default_nettype wire

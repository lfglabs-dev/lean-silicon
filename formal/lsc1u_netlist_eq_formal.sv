`default_nettype none
module lsc1u_netlist_eq_formal(
  input wire clk,
  input wire [7:0] ui_in,
  input wire [7:0] uio_in,
  input wire ena,
  input wire rst_n
);
  wire [7:0] rtl_uo, rtl_uio_out, rtl_uio_oe;
  wire [7:0] gate_uo, gate_uio_out, gate_uio_oe;

  lsc1u_rtl rtl(.ui_in(ui_in), .uo_out(rtl_uo), .uio_in(uio_in),
    .uio_out(rtl_uio_out), .uio_oe(rtl_uio_oe), .ena(ena), .clk(clk), .rst_n(rst_n));
  lsc1u_gate gate(.ui_in(ui_in), .uo_out(gate_uo), .uio_in(uio_in),
    .uio_out(gate_uio_out), .uio_oe(gate_uio_oe), .ena(ena), .clk(clk), .rst_n(rst_n),
    .VPWR(1'b1), .VGND(1'b0));

  reg past_valid = 1'b0;
  always @(posedge clk) begin
    past_valid <= 1'b1;
    if (!past_valid) assume(!rst_n);
    if (past_valid) begin
      assert(rtl_uo == gate_uo);
      assert(rtl_uio_out == gate_uio_out);
      assert(rtl_uio_oe == gate_uio_oe);
    end
  end
endmodule
`default_nettype wire

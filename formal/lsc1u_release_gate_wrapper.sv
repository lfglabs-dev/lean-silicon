`default_nettype none
module lsc1u_gate(
  input wire [7:0] ui_in, output wire [7:0] uo_out,
  input wire [7:0] uio_in, output wire [7:0] uio_out,
  output wire [7:0] uio_oe, input wire ena, input wire clk, input wire rst_n
);
  lsc1u_gate_raw raw(.ui_in(ui_in), .uo_out(uo_out), .uio_in(uio_in),
    .uio_out(uio_out), .uio_oe(uio_oe), .ena(ena), .clk(clk), .rst_n(rst_n),
    .VPWR(1'b1), .VGND(1'b0));
endmodule
`default_nettype wire

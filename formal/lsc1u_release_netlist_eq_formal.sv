`default_nettype none
module lsc1u_release_netlist_eq_formal(
  input wire clk, input wire [7:0] ui_in, input wire [7:0] uio_in,
  input wire ena, input wire rst_n
);
  wire [7:0] rtl_uo, rtl_uio_out, rtl_uio_oe;
  wire [7:0] gate_uo, gate_uio_out, gate_uio_oe;
  wire [3:0] rtl_state, gate_state;
  wire [3:0] rtl_byte_index, gate_byte_index;
  wire [7:0] rtl_saved_byte, gate_saved_byte;
  wire [7:0] rtl_out_byte, gate_out_byte;
  wire rtl_out_valid, gate_out_valid;
  wire rtl_fault_reg, gate_fault_reg;
  wire rtl_done_reg, gate_done_reg;
  wire [127:0] rtl_multiplier_impl_a_shift, gate_multiplier_impl_a_shift;
  wire [127:0] rtl_multiplier_impl_accumulator, gate_multiplier_impl_accumulator;
  lsc1u_rtl rtl(
    .ui_in(ui_in), .uo_out(rtl_uo), .uio_in(uio_in),
    .uio_out(rtl_uio_out), .uio_oe(rtl_uio_oe), .ena(ena), .clk(clk), .rst_n(rst_n),
    .\core.state (rtl_state),
    .\core.byte_index (rtl_byte_index),
    .\core.saved_byte (rtl_saved_byte),
    .\core.out_byte (rtl_out_byte),
    .\core.out_valid (rtl_out_valid),
    .\core.fault_reg (rtl_fault_reg),
    .\core.done_reg (rtl_done_reg),
    .\core.multiplier.impl.a_shift (rtl_multiplier_impl_a_shift),
    .\core.multiplier.impl.accumulator (rtl_multiplier_impl_accumulator)
  );
  lsc1u_gate gate(
    .ui_in(ui_in), .uo_out(gate_uo), .uio_in(uio_in),
    .uio_out(gate_uio_out), .uio_oe(gate_uio_oe), .ena(ena), .clk(clk), .rst_n(rst_n),
    .state(gate_state),
    .byte_index(gate_byte_index),
    .saved_byte(gate_saved_byte),
    .out_byte(gate_out_byte),
    .out_valid(gate_out_valid),
    .fault_reg(gate_fault_reg),
    .done_reg(gate_done_reg),
    .multiplier_impl_a_shift(gate_multiplier_impl_a_shift),
    .multiplier_impl_accumulator(gate_multiplier_impl_accumulator)
  );
  reg past_valid = 1'b0;
  reg [1:0] mul_retired_count = 2'd0;
  reg valid_transaction_active = 1'b0;
  reg [1:0] valid_transaction_count = 2'd0;
  always @(posedge clk) begin
    past_valid <= 1'b1;
    if (!rst_n || !ena)
      mul_retired_count <= 2'd0;
    else if (rtl_state == 4'd7 && rtl_byte_index == 4'd15 &&
             rtl_out_valid && uio_in[3] && mul_retired_count != 2'd3)
      mul_retired_count <= mul_retired_count + 1'b1;
    if (!rst_n || !ena) begin
      valid_transaction_active <= 1'b0;
      valid_transaction_count <= 2'd0;
    end else begin
      if (rtl_state == 4'd0 && rtl_uio_out[1] && uio_in[0] &&
          (ui_in == 8'h01 || ui_in == 8'h02 || ui_in == 8'h03))
        valid_transaction_active <= 1'b1;
      if (rtl_done_reg && valid_transaction_active) begin
        valid_transaction_active <= 1'b0;
        if (valid_transaction_count != 2'd3)
          valid_transaction_count <= valid_transaction_count + 1'b1;
      end
    end
    if (!past_valid) assume(!rst_n);
    if (past_valid) begin
      assert(rtl_uo == gate_uo);
      assert(rtl_uio_out == gate_uio_out);
      assert(rtl_uio_oe == gate_uio_oe);
      state_correspondence: assert({
        rtl_state, rtl_byte_index, rtl_saved_byte, rtl_out_byte,
        rtl_out_valid, rtl_fault_reg, rtl_done_reg,
        rtl_multiplier_impl_a_shift, rtl_multiplier_impl_accumulator
      } == {
        gate_state, gate_byte_index, gate_saved_byte, gate_out_byte,
        gate_out_valid, gate_fault_reg, gate_done_reg,
        gate_multiplier_impl_a_shift, gate_multiplier_impl_accumulator
      });
      cover(rst_n);
      cover(rst_n && (rtl_uo != 0 || rtl_uio_out != 0 || rtl_uio_oe != 0));
      cover(mul_retired_count >= 2'd1);
      cover(valid_transaction_count >= 2'd2);
    end
  end
endmodule
`default_nettype wire

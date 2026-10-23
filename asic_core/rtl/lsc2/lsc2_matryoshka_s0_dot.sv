// =============================================================================
// Lean-Silicon Core v2 (LSC-2) — 4-Stage Pre-Biased Pipelined Matryoshka S0 INT8 Dot + ClippedReLU^2
// Bit-exact match for `lean_native_trm_matryoshka_ref_int8`
//   Stage 1: 16 individual INT8*INT8 signed products -> `prod0_q..prod3_q` per quad (pure DSP -> FF)
//   Stage 2: 4-way quad sums -> `quad_sum_q[0..3]`
//   Stage 3: 4-way quad tree sum -> `acc_s3_q` AND pre-biased `(acc_s3_c - 1408) >>> 7` -> `pre_s3_q`
//   Stage 4: Pure saturation + 17-entry LUT for ClippedReLU^2 on `pre_s3_q` -> `act_u8` (zero CCU2C carry chain)
// =============================================================================
`timescale 1ns / 1ps

module lsc2_matryoshka_s0_dot (
  input  logic                clk,
  input  logic                rst_n,
  input  logic                start,
  input  logic        [127:0] h_norm_packed,
  input  logic        [127:0] w1_col_packed,
  output logic                busy,
  output logic                done_pulse,
  output logic         [7:0]  act_u8,
  output logic signed [31:0]  acc_q,
  output logic signed [31:0]  pre_q,
  output logic signed [31:0]  relu_q
);
  logic signed [15:0] prod0_q [0:3];
  logic signed [15:0] prod1_q [0:3];
  logic signed [15:0] prod2_q [0:3];
  logic signed [15:0] prod3_q [0:3];
  logic signed [17:0] quad_sum_c [0:3];
  logic signed [17:0] quad_sum_q [0:3];
  logic               s1_valid_q;
  logic               s2_valid_q;
  logic               s3_valid_q;
  logic signed [31:0] acc_s3_c, acc_s3_q;
  logic signed [31:0] pre_s3_c, pre_s3_q;

  logic signed [31:0] relu_c;
  logic        [7:0]  act_c;

  assign busy = start | s1_valid_q | s2_valid_q | s3_valid_q;

  genvar g;
  generate
    for (g = 0; g < 4; g = g + 1) begin : g_quad
      wire signed [7:0] h0 = h_norm_packed[(4*g+0)*8 +: 8];
      wire signed [7:0] h1 = h_norm_packed[(4*g+1)*8 +: 8];
      wire signed [7:0] h2 = h_norm_packed[(4*g+2)*8 +: 8];
      wire signed [7:0] h3 = h_norm_packed[(4*g+3)*8 +: 8];
      wire signed [7:0] w0 = w1_col_packed[(4*g+0)*8 +: 8];
      wire signed [7:0] w1 = w1_col_packed[(4*g+1)*8 +: 8];
      wire signed [7:0] w2 = w1_col_packed[(4*g+2)*8 +: 8];
      wire signed [7:0] w3 = w1_col_packed[(4*g+3)*8 +: 8];
      wire signed [15:0] p0 = h0 * w0;
      wire signed [15:0] p1 = h1 * w1;
      wire signed [15:0] p2 = h2 * w2;
      wire signed [15:0] p3 = h3 * w3;

      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
          prod0_q[g] <= 16'sd0;
          prod1_q[g] <= 16'sd0;
          prod2_q[g] <= 16'sd0;
          prod3_q[g] <= 16'sd0;
        end else if (start) begin
          prod0_q[g] <= p0;
          prod1_q[g] <= p1;
          prod2_q[g] <= p2;
          prod3_q[g] <= p3;
        end
      end

      assign quad_sum_c[g] = ($signed({{2{prod0_q[g][15]}}, prod0_q[g]})
                            + $signed({{2{prod1_q[g][15]}}, prod1_q[g]}))
                           + ($signed({{2{prod2_q[g][15]}}, prod2_q[g]})
                            + $signed({{2{prod3_q[g][15]}}, prod3_q[g]}));
    end
  endgenerate

  always_comb begin
    acc_s3_c = ($signed({{14{quad_sum_q[0][17]}}, quad_sum_q[0]})
              + $signed({{14{quad_sum_q[1][17]}}, quad_sum_q[1]}))
             + ($signed({{14{quad_sum_q[2][17]}}, quad_sum_q[2]})
              + $signed({{14{quad_sum_q[3][17]}}, quad_sum_q[3]}));
    pre_s3_c = (acc_s3_c >>> 7) - 32'sd11;
    if (pre_s3_q <= 0) begin
      relu_c = 32'sd0;
      act_c  = 8'd0;
    end else if (pre_s3_q >= 16) begin
      relu_c = 32'sd16;
      act_c  = 8'd255;
    end else begin
      relu_c = pre_s3_q;
      case (pre_s3_q[3:0])
        4'd1:  act_c = 8'd1;
        4'd2:  act_c = 8'd4;
        4'd3:  act_c = 8'd9;
        4'd4:  act_c = 8'd16;
        4'd5:  act_c = 8'd25;
        4'd6:  act_c = 8'd36;
        4'd7:  act_c = 8'd49;
        4'd8:  act_c = 8'd64;
        4'd9:  act_c = 8'd81;
        4'd10: act_c = 8'd100;
        4'd11: act_c = 8'd121;
        4'd12: act_c = 8'd144;
        4'd13: act_c = 8'd169;
        4'd14: act_c = 8'd196;
        4'd15: act_c = 8'd225;
        default: act_c = 8'd0;
      endcase
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      quad_sum_q[0] <= 18'sd0;
      quad_sum_q[1] <= 18'sd0;
      quad_sum_q[2] <= 18'sd0;
      quad_sum_q[3] <= 18'sd0;
      s1_valid_q    <= 1'b0;
      s2_valid_q    <= 1'b0;
      s3_valid_q    <= 1'b0;
      acc_s3_q      <= 32'sd0;
      pre_s3_q      <= 32'sd0;
      done_pulse    <= 1'b0;
      act_u8        <= 8'd0;
      acc_q         <= 32'sd0;
      pre_q         <= 32'sd0;
      relu_q        <= 32'sd0;
    end else begin
      s1_valid_q <= start;
      s2_valid_q <= s1_valid_q;
      if (s1_valid_q) begin
        quad_sum_q[0] <= quad_sum_c[0];
        quad_sum_q[1] <= quad_sum_c[1];
        quad_sum_q[2] <= quad_sum_c[2];
        quad_sum_q[3] <= quad_sum_c[3];
      end
      s3_valid_q <= s2_valid_q;
      if (s2_valid_q) begin
        acc_s3_q <= acc_s3_c;
        pre_s3_q <= pre_s3_c;
      end
      done_pulse <= s3_valid_q;
      if (s3_valid_q) begin
        acc_q  <= acc_s3_q;
        pre_q  <= pre_s3_q;
        relu_q <= relu_c;
        act_u8 <= act_c;
      end
    end
  end
endmodule

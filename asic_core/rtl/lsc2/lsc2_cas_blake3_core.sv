// =============================================================================
// Lean-Silicon Core v2 (LSC-2) — 4-Stage 16x16-Limb Mix64 CAS Gate & 4-Stage BLAKE3 G-Unit
// Decomposes 64-bit constant multiplication into 10 pure 16x16->32 single-DSP
// products (`MULT18X18D`) in Stage 1 with zero combinational CCU2C carry chain,
// followed by registered column compression in Stages 2 and 3, and pipelines
// `lsc2_blake3_g_unit` into 4 quarter-round stages (at most one 32-bit adder per stage).
// =============================================================================
`timescale 1ns / 1ps

module lsc2_mul64_const_pipe4 #(
  parameter logic [63:0] CONST_K = 64'hBF58476D1CE4E5B9
) (
  input  logic        clk,
  input  logic        rst_n,
  input  logic [63:0] x,
  output logic [63:0] out_q
);
  localparam logic [15:0] C0 = CONST_K[15:0];
  localparam logic [15:0] C1 = CONST_K[31:16];
  localparam logic [15:0] C2 = CONST_K[47:32];
  localparam logic [15:0] C3 = CONST_K[63:48];

  logic [63:0] x_s0_q;

  // Stage 1: 10 parallel 16x16 -> 32-bit products (each fits in a single MULT18X18D)
  logic [31:0] m00_q, m01_q, m10_q, m02_q, m11_q, m20_q;
  logic [15:0] m03_lo_q, m12_lo_q, m21_lo_q, m30_lo_q;

  wire [31:0] m00_w = x_s0_q[15:0]  * C0;
  wire [31:0] m01_w = x_s0_q[15:0]  * C1;
  wire [31:0] m10_w = x_s0_q[31:16] * C0;
  wire [31:0] m02_w = x_s0_q[15:0]  * C2;
  wire [31:0] m11_w = x_s0_q[31:16] * C1;
  wire [31:0] m20_w = x_s0_q[47:32] * C0;
  wire [31:0] m03_w = x_s0_q[15:0]  * C3;
  wire [31:0] m12_w = x_s0_q[31:16] * C2;
  wire [31:0] m21_w = x_s0_q[47:32] * C1;
  wire [31:0] m30_w = x_s0_q[63:48] * C0;

  // Stage 2: balanced pairwise column sums
  logic [63:0] sum_a_s2_q, sum_b_s2_q, sum_c_s2_q;

  wire [63:0] term_col0 = {32'd0, m00_q};
  wire [63:0] term_col1 = ({32'd0, m01_q} + {32'd0, m10_q}) << 16;
  wire [63:0] term_col2 = ({32'd0, m02_q} + {32'd0, m11_q} + {32'd0, m20_q}) << 32;
  wire [15:0] col3_sum16 = (m03_lo_q + m12_lo_q) + (m21_lo_q + m30_lo_q);
  wire [63:0] term_col3 = {col3_sum16, 48'd0};

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      x_s0_q     <= 64'd0;
      m00_q      <= 32'd0;
      m01_q      <= 32'd0;
      m10_q      <= 32'd0;
      m02_q      <= 32'd0;
      m11_q      <= 32'd0;
      m20_q      <= 32'd0;
      m03_lo_q   <= 16'd0;
      m12_lo_q   <= 16'd0;
      m21_lo_q   <= 16'd0;
      m30_lo_q   <= 16'd0;
      sum_a_s2_q <= 64'd0;
      sum_b_s2_q <= 64'd0;
      sum_c_s2_q <= 64'd0;
      out_q      <= 64'd0;
    end else begin
      x_s0_q     <= x;
      m00_q      <= m00_w;
      m01_q      <= m01_w;
      m10_q      <= m10_w;
      m02_q      <= m02_w;
      m11_q      <= m11_w;
      m20_q      <= m20_w;
      m03_lo_q   <= m03_w[15:0];
      m12_lo_q   <= m12_w[15:0];
      m21_lo_q   <= m21_w[15:0];
      m30_lo_q   <= m30_w[15:0];
      sum_a_s2_q <= term_col0 + term_col1;
      sum_b_s2_q <= term_col2;
      sum_c_s2_q <= term_col3;
      out_q      <= (sum_a_s2_q + sum_b_s2_q) + sum_c_s2_q;
    end
  end
endmodule

module lsc2_mix64_cas_gate (
  input  logic        clk,
  input  logic        rst_n,
  input  logic [63:0] acc,
  input  logic [63:0] word,
  input  logic [63:0] actual_hash,
  input  logic [63:0] expected_hash,
  input  logic        has_path_traversal,
  output logic [63:0] mix_out,
  output logic        verify_cas_digest
);
  localparam logic [63:0] GOLDEN = 64'h9E3779B97F4A7C15;
  localparam logic [63:0] MIX_M1 = 64'hBF58476D1CE4E5B9;
  localparam logic [63:0] MIX_M2 = 64'h94D049BB133111EB;

  logic [63:0] z1_q;
  wire  [63:0] z2_q, z3_q;
  logic [9:0]  cas_ok_pipe_q;

  lsc2_mul64_const_pipe4 #(.CONST_K(MIX_M1)) u_mul_m1 (
    .clk  (clk),
    .rst_n(rst_n),
    .x    (z1_q ^ (z1_q >> 30)),
    .out_q(z2_q)
  );

  lsc2_mul64_const_pipe4 #(.CONST_K(MIX_M2)) u_mul_m2 (
    .clk  (clk),
    .rst_n(rst_n),
    .x    (z2_q ^ (z2_q >> 27)),
    .out_q(z3_q)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      z1_q              <= 64'd0;
      mix_out           <= 64'd0;
      cas_ok_pipe_q     <= 10'd0;
      verify_cas_digest <= 1'b0;
    end else begin
      z1_q              <= (acc ^ word) + GOLDEN;
      cas_ok_pipe_q[0]  <= (actual_hash == expected_hash) && !has_path_traversal;
      cas_ok_pipe_q[9:1]<= cas_ok_pipe_q[8:0];
      mix_out           <= z3_q ^ (z3_q >> 31);
      verify_cas_digest <= cas_ok_pipe_q[8];
    end
  end
endmodule

module lsc2_blake3_g_unit (
  input  logic        clk,
  input  logic        rst_n,
  input  logic [31:0] a, b, c, d, mx, my,
  output logic [31:0] a_o, b_o, c_o, d_o
);
  function automatic logic [31:0] rotr32(input logic [31:0] x, input int unsigned n);
    rotr32 = (x >> n) | (x << (32 - n));
  endfunction

  // Stage 0: pre-sum (a + mx) and register inputs so no stage has a 3-input 32-bit adder
  logic [31:0] amx_s0_q, b_s0_q, c_s0_q, d_s0_q, my_s0_q;
  // Stage 1: a1 = amx_s0_q + b_s0_q, d1 = rotr32(d_s0_q ^ a1, 16)
  logic [31:0] a1_s1_q, d1_s1_q, b_s1_q, c_s1_q, my_s1_q;
  // Stage 2: c1 = c_s1_q + d1_s1_q, b1 = rotr32(b_s1_q ^ c1, 12), amy = a1_s1_q + my_s1_q
  logic [31:0] amy_s2_q, b1_s2_q, c1_s2_q, d1_s2_q;
  // Stage 3: a2 = amy_s2_q + b1_s2_q, d2 = rotr32(d1_s2_q ^ a2, 8)
  logic [31:0] a2_s3_q, d2_s3_q, b1_s3_q, c1_s3_q;

  wire [31:0] a1_c = amx_s0_q + b_s0_q;
  wire [31:0] c1_c = c_s1_q + d1_s1_q;
  wire [31:0] a2_c = amy_s2_q + b1_s2_q;
  wire [31:0] c2_c = c1_s3_q + d2_s3_q;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      amx_s0_q <= 32'd0; b_s0_q  <= 32'd0; c_s0_q  <= 32'd0; d_s0_q  <= 32'd0; my_s0_q <= 32'd0;
      a1_s1_q  <= 32'd0; d1_s1_q <= 32'd0; b_s1_q  <= 32'd0; c_s1_q  <= 32'd0; my_s1_q <= 32'd0;
      amy_s2_q <= 32'd0; b1_s2_q <= 32'd0; c1_s2_q <= 32'd0; d1_s2_q <= 32'd0;
      a2_s3_q  <= 32'd0; d2_s3_q <= 32'd0; b1_s3_q <= 32'd0; c1_s3_q <= 32'd0;
      a_o      <= 32'd0; b_o     <= 32'd0; c_o     <= 32'd0; d_o     <= 32'd0;
    end else begin
      // Stage 0: single 2-input 32-bit adder (a + mx)
      amx_s0_q <= a + mx;
      b_s0_q   <= b;
      c_s0_q   <= c;
      d_s0_q   <= d;
      my_s0_q  <= my;

      // Stage 1: single 2-input 32-bit adder (amx_s0_q + b_s0_q) + XOR/rotr16
      a1_s1_q  <= a1_c;
      d1_s1_q  <= rotr32(d_s0_q ^ a1_c, 16);
      b_s1_q   <= b_s0_q;
      c_s1_q   <= c_s0_q;
      my_s1_q  <= my_s0_q;

      // Stage 2: parallel independent 2-input 32-bit adders (c_s1_q + d1_s1_q) and (a1_s1_q + my_s1_q)
      c1_s2_q  <= c1_c;
      b1_s2_q  <= rotr32(b_s1_q ^ c1_c, 12);
      amy_s2_q <= a1_s1_q + my_s1_q;
      d1_s2_q  <= d1_s1_q;

      // Stage 3: single 2-input 32-bit adder (amy_s2_q + b1_s2_q) + XOR/rotr8
      a2_s3_q  <= a2_c;
      d2_s3_q  <= rotr32(d1_s2_q ^ a2_c, 8);
      b1_s3_q  <= b1_s2_q;
      c1_s3_q  <= c1_s2_q;

      // Stage 4: single 2-input 32-bit adder (c1_s3_q + d2_s3_q) + XOR/rotr7
      a_o      <= a2_s3_q;
      d_o      <= d2_s3_q;
      c_o      <= c2_c;
      b_o      <= rotr32(b1_s3_q ^ c2_c, 7);
    end
  end
endmodule

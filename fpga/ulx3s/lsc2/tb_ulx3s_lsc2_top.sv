// =============================================================================
// Self-Checking End-to-End Testbench for ULX3S LSC-2 & Matryoshka S0 Engine
// Verifies bit-exact equivalence against C reference (`lean_native_runtime.c`)
// =============================================================================
`timescale 1ns / 1ps

module tb_ulx3s_lsc2_top;
  logic clk = 1'b0;
  always #20 clk = ~clk; // 25 MHz (40 ns period)

  logic rst_n;
  int   errors = 0;
  int   checks = 0;

  // ---------------------------------------------------------------------------
  // 1. Direct verification of `lsc2_matryoshka_s0_engine` (32 columns + W2 row)
  // ---------------------------------------------------------------------------
  logic               eng_start;
  logic       [127:0] eng_h_norm;
  logic       [127:0] eng_w1_cols [0:31];
  logic       [127:0] eng_w1_cur;
  logic       [255:0] eng_w2_row;
  logic signed [31:0] eng_z_in, eng_y_in;
  logic         [4:0] eng_req_col;
  logic               eng_busy, eng_done;
  logic       [255:0] eng_act_vec;
  logic signed [31:0] eng_delta_q, eng_z_next_q, eng_y_next_q;

  assign eng_w1_cur = eng_w1_cols[eng_req_col];

  lsc2_matryoshka_s0_engine u_eng (
    .clk           (clk),
    .rst_n         (rst_n),
    .start         (eng_start),
    .h_norm_packed (eng_h_norm),
    .w1_col_packed (eng_w1_cur),
    .w2_row_packed (eng_w2_row),
    .z_in          (eng_z_in),
    .y_in          (eng_y_in),
    .req_col_idx   (eng_req_col),
    .busy          (eng_busy),
    .done_pulse    (eng_done),
    .act_vec_packed(eng_act_vec),
    .delta_q       (eng_delta_q),
    .z_next_q      (eng_z_next_q),
    .y_next_q      (eng_y_next_q)
  );

  // ---------------------------------------------------------------------------
  // 2. Direct verification of `ulx3s_lsc2_top`
  // ---------------------------------------------------------------------------
  logic [6:0] top_btn;
  logic [7:0] top_led;
  logic       top_ftdi_txd = 1'b1;
  logic       top_ftdi_rxd;
  assign top_btn[0]   = rst_n;
  assign top_btn[6:1] = 6'b000100;

  ulx3s_lsc2_top u_top (
    .clk_25mhz(clk),
    .btn      (top_btn),
    .led      (top_led),
    .ftdi_txd (top_ftdi_txd),
    .ftdi_rxd (top_ftdi_rxd)
  );

  // C reference helper for 16-element INT8 dot + ClippedReLU^2
  function automatic logic [7:0] ref_col_act_u8(
    input logic [127:0] h_pack,
    input logic [127:0] w_pack
  );
    int signed acc;
    int signed pre;
    int signed relu;
    int unsigned sq;
    logic signed [7:0] hi;
    logic signed [7:0] wi;
    acc = 0;
    for (int i = 0; i < 16; i++) begin
      hi = h_pack[i*8 +: 8];
      wi = w_pack[i*8 +: 8];
      acc += int'(hi) * int'(wi);
    end
    pre = (acc >>> 7) - 11;
    if (pre <= 0) relu = 0;
    else if (pre > 16) relu = 16;
    else relu = pre;
    sq = relu * relu;
    return (sq > 255) ? 8'd255 : sq[7:0];
  endfunction

  // C reference helper for SplitMix64 (`lean_native_mix64_word`)
  function automatic logic [63:0] ref_mix64_word(
    input logic [63:0] acc,
    input logic [63:0] word
  );
    logic [63:0] z;
    z = (acc ^ word) + 64'h9E3779B97F4A7C15;
    z = (z ^ (z >> 30)) * 64'hBF58476D1CE4E5B9;
    z = (z ^ (z >> 27)) * 64'h94D049BB133111EB;
    return z ^ (z >> 31);
  endfunction

  int timeout;
  logic [255:0] exp_act_vec;
  int signed    exp_delta;
  int signed    exp_z_next;
  int signed    exp_y_next;
  logic [7:0]   a_u8;
  logic signed [7:0] w2_s8;
  int           t_top;
  bit           saw_fc_done;
  bit           saw_trm_done;
  logic [63:0]  exp_cas_mix;

  initial begin
    rst_n     = 1'b0;
    eng_start = 1'b0;
    eng_h_norm = 128'h7F_7F_7F_7F_7F_7F_7F_7F_7F_7F_7F_7F_7F_7F_7F_7F;
    eng_w2_row = 256'h05_FA_03_FD_07_F9_02_FE_04_FC_06_FA_01_FF_08_F8_03_FD_05_FB_02_FE_07_F9_04_FC_01_FF_06_FA_02_FE;
    eng_z_in   = 32'sd420;
    eng_y_in   = -32'sd180;
    for (int j = 0; j < 32; j++) begin
      eng_w1_cols[j] = {32'(32'h10101010 + j * 32'h01010101), 32'(32'h20202020 + j * 32'h01010101), 32'(32'h18181818 + j * 32'h01010101), 32'(32'h14141414 + j * 32'h01010101)};
    end

    repeat (4) @(posedge clk);
    rst_n = 1'b1;
    repeat (2) @(posedge clk);

    // Trigger Matryoshka S0 Engine
    @(negedge clk);
    eng_start = 1'b1;
    @(negedge clk);
    eng_start = 1'b0;

    timeout = 0;
    while (!eng_done && timeout < 128) begin
      @(posedge clk);
      timeout++;
    end
    checks++;
    if (!eng_done) begin
      $display("FAIL: lsc2_matryoshka_s0_engine timed out");
      errors++;
    end

    // Compute exact C reference
    exp_delta = 0;
    for (int j = 0; j < 32; j++) begin
      a_u8  = ref_col_act_u8(eng_h_norm, eng_w1_cols[j]);
      w2_s8 = eng_w2_row[j*8 +: 8];
      exp_act_vec[j*8 +: 8] = a_u8;
      exp_delta += int'(a_u8) * int'(w2_s8);
    end
    exp_z_next = eng_z_in + (exp_delta >>> 9);
    exp_y_next = (eng_y_in + exp_z_next) >>> 1;

    checks++;
    if (eng_act_vec !== exp_act_vec) begin
      $display("FAIL: act_vec mismatch got=%h exp=%h", eng_act_vec, exp_act_vec);
      errors++;
    end
    checks++;
    if (eng_delta_q !== exp_delta) begin
      $display("FAIL: delta_q mismatch got=%0d exp=%0d", eng_delta_q, exp_delta);
      errors++;
    end
    checks++;
    if (eng_z_next_q !== exp_z_next || eng_y_next_q !== exp_y_next) begin
      $display("FAIL: z/y mismatch got=(%0d,%0d) exp=(%0d,%0d)", eng_z_next_q, eng_y_next_q, exp_z_next, exp_y_next);
      errors++;
    end

    // Fast-forward u_top.heartbeat_q to trigger top-level start_pulse_q -> fc_done -> trm_done
    @(negedge clk);
    u_top.heartbeat_q = 24'h00_0000;
    t_top = 0;
    saw_fc_done  = 0;
    saw_trm_done = 0;
    while (t_top < 1200 && !saw_trm_done) begin
      @(posedge clk);
      if (u_top.fc_done)  saw_fc_done  = 1;
      if (u_top.trm_done) saw_trm_done = 1;
      t_top++;
    end
    checks++;
    if (!saw_fc_done || !saw_trm_done) begin
      $display("FAIL: u_top pipeline did not complete (fc_done=%0b trm_done=%0b)", saw_fc_done, saw_trm_done);
      errors++;
    end
    checks++;
    if ($isunknown(top_led) || (top_ftdi_rxd !== (top_ftdi_txd ^ top_led[0]))) begin
      $display("FAIL: top_led/top_ftdi_rxd invalid");
      errors++;
    end

    // Wait 8 cycles for u_cas pipeline to settle and verify bit-exact SplitMix64 output
    repeat (14) @(posedge clk);
    exp_cas_mix = ref_mix64_word(u_top.fc_sample_idx, u_top.seed_q);
    checks++;
    if (u_top.cas_mix_out !== exp_cas_mix) begin
      $display("FAIL: u_cas mix_out mismatch got=%h exp=%h", u_top.cas_mix_out, exp_cas_mix);
      errors++;
    end

    if (errors == 0) begin
      $display("PASS: tb_ulx3s_lsc2_top ALL %0d CHECKS PASSED (bit-exact, delta=%0d, z_next=%0d, y_next=%0d, cas_mix=%h)", checks, eng_delta_q, eng_z_next_q, eng_y_next_q, u_top.cas_mix_out);
    end else begin
      $display("FAIL: %0d errors out of %0d checks", errors, checks);
    end
    $finish;
  end
endmodule

// =============================================================================
// ULX3S LFE5U-85F Top-Level Wrapper for Lean-Silicon Core v2 (LSC-2)
// Integrates:
//   1. `lsc2_fastcheck_u256_core` (Pipelined SplitMix64 + 16-op RPN ALU)
//   2. `lsc2_mix64_cas_gate` + `lsc2_blake3_g_unit`
//   3. `lsc2_matryoshka_s0_engine` (32-col streaming INT8 dot + ClippedReLU^2 + W2 delta/z/y)
// =============================================================================
`timescale 1ns / 1ps

module ulx3s_lsc2_top (
    input  wire        clk_25mhz,
    input  wire [6:0]  btn,
    output wire [7:0]  led,
    input  wire        ftdi_txd,
    output wire        ftdi_rxd
);
    wire rst_n = btn[0];
    reg  [23:0] heartbeat_q;
    reg         start_pulse_q;
    reg  [63:0] seed_q;
    reg  [31:0] sample_limit_q;

    always @(posedge clk_25mhz or negedge rst_n) begin
        if (!rst_n) begin
            heartbeat_q    <= 24'd0;
            start_pulse_q  <= 1'b0;
            seed_q         <= 64'h9E37_79B9_7F4A_7C15;
            sample_limit_q <= 32'd64;
        end else begin
            heartbeat_q   <= heartbeat_q + 24'd1;
            start_pulse_q <= (heartbeat_q[15:0] == 16'h0001);
            if (start_pulse_q) begin
                seed_q <= seed_q + 64'h0000_0000_0000_0001;
            end
        end
    end

    wire        fc_busy, fc_done, fc_found;
    wire [63:0] fc_sample_idx;

    lsc2_fastcheck_u256_core u_fastcheck (
        .clk           (clk_25mhz),
        .rst_n         (rst_n),
        .start         (start_pulse_q),
        .base_seed     (seed_q),
        .goal_idx      ({58'd0, btn[6:1]}),
        .n_samples     (sample_limit_q),
        .rpn_packed    (64'h0000_0000_4010_0201),
        .arg0          (64'd1),
        .arg1          (64'd1),
        .busy          (fc_busy),
        .done_pulse    (fc_done),
        .cex_found     (fc_found),
        .min_sample_idx(fc_sample_idx)
    );

    wire [63:0] cas_mix_out;
    wire        cas_ok;
    lsc2_mix64_cas_gate u_cas (
        .clk               (clk_25mhz),
        .rst_n             (rst_n),
        .acc               (fc_sample_idx),
        .word              (seed_q),
        .actual_hash       (fc_sample_idx ^ seed_q),
        .expected_hash     (fc_sample_idx ^ seed_q),
        .has_path_traversal(btn[1]),
        .mix_out           (cas_mix_out),
        .verify_cas_digest (cas_ok)
    );

    wire [31:0] b3_a, b3_b, b3_c, b3_d;
    lsc2_blake3_g_unit u_blake3_g (
        .clk  (clk_25mhz),
        .rst_n(rst_n),
        .a    (cas_mix_out[31:0]),
        .b    (cas_mix_out[63:32]),
        .c    (fc_sample_idx[31:0]),
        .d    (fc_sample_idx[63:32]),
        .mx   (seed_q[31:0]),
        .my   (seed_q[63:32]),
        .a_o  (b3_a),
        .b_o  (b3_b),
        .c_o  (b3_c),
        .d_o  (b3_d)
    );

    wire         [4:0]  trm_col_idx;
    wire                trm_busy, trm_done;
    wire        [255:0] trm_act_vec;
    wire signed  [31:0] trm_delta_q, trm_z_next_q, trm_y_next_q;

    lsc2_matryoshka_s0_engine u_trm_engine (
        .clk           (clk_25mhz),
        .rst_n         (rst_n),
        .start         (fc_done),
        .h_norm_packed ({fc_sample_idx, cas_mix_out}),
        .w1_col_packed ({seed_q ^ {59'd0, trm_col_idx}, {b3_d, b3_c} ^ {59'd0, trm_col_idx}}),
        .w2_row_packed ({seed_q, cas_mix_out, {b3_d, b3_c}, {b3_b, b3_a}}),
        .z_in          (b3_a),
        .y_in          (b3_b),
        .req_col_idx   (trm_col_idx),
        .busy          (trm_busy),
        .done_pulse    (trm_done),
        .act_vec_packed(trm_act_vec),
        .delta_q       (trm_delta_q),
        .z_next_q      (trm_z_next_q),
        .y_next_q      (trm_y_next_q)
    );

    reg [7:0] status_q;
    always @(posedge clk_25mhz or negedge rst_n) begin
        if (!rst_n) begin
            status_q <= 8'd0;
        end else begin
            status_q <= {
                heartbeat_q[23],
                fc_busy | trm_busy,
                fc_found,
                cas_ok,
                trm_done,
                b3_a[0] ^ b3_b[0] ^ b3_c[0] ^ b3_d[0],
                trm_z_next_q[0] ^ trm_y_next_q[0],
                trm_act_vec[0] ^ trm_delta_q[0]
            };
        end
    end

    assign led      = status_q;
    assign ftdi_rxd = ftdi_txd ^ status_q[0];
endmodule

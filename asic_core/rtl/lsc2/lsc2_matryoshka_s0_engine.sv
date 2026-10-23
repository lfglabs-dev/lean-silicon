// =============================================================================
// Lean-Silicon Core v2 (LSC-2) — Matryoshka S0 16x32 Streaming Engine
// Bit-exact match for `lean_native_trm_matryoshka_cpu_int8` lines 778-813:
//   - Streams j = 0..31 hidden columns `w1_col_packed` through `lsc2_matryoshka_s0_dot`
//   - Shifts `w2_row_q` by 8 bits per retired column (eliminates 32:1 mux before DSP)
//   - Pipelines `prod_q <= dot_act_u8 * w2_row_q[7:0]` and `delta_q <= delta_q + prod_q`
//   - Updates `z_next_q = z_in + (delta_q >>> 9)` and `y_next_q = (y_in + z_next_q) >>> 1`
// =============================================================================
`timescale 1ns / 1ps

module lsc2_matryoshka_s0_engine (
  input  logic                clk,
  input  logic                rst_n,
  input  logic                start,
  input  logic        [127:0] h_norm_packed,
  input  logic        [127:0] w1_col_packed,
  input  logic        [255:0] w2_row_packed,
  input  logic         [31:0] z_in,
  input  logic         [31:0] y_in,
  output logic          [4:0] req_col_idx,
  output logic                busy,
  output logic                done_pulse,
  output logic        [255:0] act_vec_packed,
  output logic signed  [31:0] delta_q,
  output logic signed  [31:0] z_next_q,
  output logic signed  [31:0] y_next_q
);
  typedef enum logic [1:0] {
    E_IDLE   = 2'd0,
    E_STREAM = 2'd1,
    E_DRAIN  = 2'd2,
    E_FINAL  = 2'd3
  } state_t;

  state_t             state_q;
  logic        [5:0]  issue_cnt_q;
  logic        [5:0]  retire_cnt_q;
  logic signed [31:0] z_in_q, y_in_q;
  logic        [255:0] w2_row_q;
  logic signed [31:0] prod_q;
  logic               prod_valid_q;
  logic               final_wait_q;

  logic               dot_start;
  logic               dot_busy;
  logic               dot_done;
  logic        [7:0]  dot_act_u8;
  logic signed [31:0] dot_acc_q, dot_pre_q, dot_relu_q;

  assign req_col_idx = issue_cnt_q[4:0];
  assign busy        = (state_q != E_IDLE);
  assign dot_start   = (state_q == E_STREAM) && (issue_cnt_q < 6'd32);

  lsc2_matryoshka_s0_dot u_dot (
    .clk          (clk),
    .rst_n        (rst_n),
    .start        (dot_start),
    .h_norm_packed(h_norm_packed),
    .w1_col_packed(w1_col_packed),
    .busy         (dot_busy),
    .done_pulse   (dot_done),
    .act_u8       (dot_act_u8),
    .acc_q        (dot_acc_q),
    .pre_q        (dot_pre_q),
    .relu_q       (dot_relu_q)
  );

  wire signed [7:0]  w2_cur_s8 = w2_row_q[7:0];
  wire signed [31:0] prod_c    = $signed({24'd0, dot_act_u8}) * $signed({{24{w2_cur_s8[7]}}, w2_cur_s8});
  wire signed [31:0] z_calc_c  = z_in_q + (delta_q >>> 9);
  wire signed [31:0] y_calc_c  = (y_in_q + z_calc_c) >>> 1;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state_q        <= E_IDLE;
      issue_cnt_q    <= 6'd0;
      retire_cnt_q   <= 6'd0;
      z_in_q         <= 32'sd0;
      y_in_q         <= 32'sd0;
      w2_row_q       <= 256'd0;
      act_vec_packed <= 256'd0;
      prod_q         <= 32'sd0;
      prod_valid_q   <= 1'b0;
      final_wait_q   <= 1'b0;
      delta_q        <= 32'sd0;
      z_next_q       <= 32'sd0;
      y_next_q       <= 32'sd0;
      done_pulse     <= 1'b0;
    end else begin
      done_pulse   <= 1'b0;
      prod_valid_q <= dot_done && (state_q == E_STREAM || state_q == E_DRAIN);
      if (dot_done && (state_q == E_STREAM || state_q == E_DRAIN)) begin
        prod_q <= prod_c;
      end
      if (prod_valid_q) begin
        delta_q <= delta_q + prod_q;
      end

      case (state_q)
        E_IDLE: begin
          if (start) begin
            z_in_q       <= $signed(z_in);
            y_in_q       <= $signed(y_in);
            w2_row_q     <= w2_row_packed;
            issue_cnt_q  <= 6'd0;
            retire_cnt_q <= 6'd0;
            delta_q      <= 32'sd0;
            prod_valid_q <= 1'b0;
            final_wait_q <= 1'b0;
            state_q      <= E_STREAM;
          end
        end
        E_STREAM: begin
          if (dot_done) begin
            act_vec_packed <= {dot_act_u8, act_vec_packed[255:8]};
            w2_row_q       <= {8'd0, w2_row_q[255:8]};
            retire_cnt_q   <= retire_cnt_q + 6'd1;
          end
          if (issue_cnt_q == 6'd31) begin
            issue_cnt_q <= 6'd32;
            state_q     <= E_DRAIN;
          end else begin
            issue_cnt_q <= issue_cnt_q + 6'd1;
          end
        end
        E_DRAIN: begin
          if (dot_done) begin
            act_vec_packed <= {dot_act_u8, act_vec_packed[255:8]};
            w2_row_q       <= {8'd0, w2_row_q[255:8]};
            retire_cnt_q   <= retire_cnt_q + 6'd1;
            if (retire_cnt_q == 6'd31) begin
              final_wait_q <= 1'b1;
              state_q      <= E_FINAL;
            end
          end
        end
        E_FINAL: begin
          if (final_wait_q) begin
            final_wait_q <= 1'b0;
          end else begin
            z_next_q   <= z_calc_c;
            y_next_q   <= y_calc_c;
            done_pulse <= 1'b1;
            state_q    <= E_IDLE;
          end
        end
        default: state_q <= E_IDLE;
      endcase
    end
  end
endmodule

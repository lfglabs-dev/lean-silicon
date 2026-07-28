`default_nettype none
// Bounded one-cycle correspondence milestone for the registered frontend
// boundary.  This is intentionally a reset/abort/idle relation, not a
// phase-complete release sequential-equivalence proof.
module lsc1_packet_frontend_one_cycle_boundary;
  (* anyseq *) reg clk, abort, rx_valid, tx_ready;
  (* anyseq *) reg [7:0] rx_data;
  wire rx_ready, tx_valid, busy, fault, done_pulse;
  wire [7:0] tx_data;
  wire [3:0] arch_phase;
  wire arch_parser_busy, arch_tx_busy, arch_alu_busy, arch_encoder_busy;
  wire arch_tx_start, arch_capture_result_crc, arch_alu_start, arch_encoder_start;
  wire arch_result_pending, arch_state_valid, arch_fault, arch_done_pulse;
  wire [31:0] arch_staged_txn_id, arch_staged_next_pc, arch_staged_next_fp;
  wire [31:0] arch_staged_result_crc, arch_committed_pc, arch_committed_fp, arch_retire_seq;
  wire [7:0] arch_active_profile, arch_last_status, arch_last_fault;
  wire rst_n = 1'b1;
  reg past_valid;

  lsc1_packet_frontend dut (
    .clk(clk), .rst_n(rst_n), .abort(abort), .rx_data(rx_data),
    .rx_valid(rx_valid), .rx_ready(rx_ready), .tx_data(tx_data),
    .tx_valid(tx_valid), .tx_ready(tx_ready), .busy(busy), .fault(fault),
    .done_pulse(done_pulse), .arch_phase(arch_phase),
    .arch_parser_busy(arch_parser_busy), .arch_tx_busy(arch_tx_busy),
    .arch_alu_busy(arch_alu_busy), .arch_encoder_busy(arch_encoder_busy),
    .arch_tx_start(arch_tx_start), .arch_capture_result_crc(arch_capture_result_crc),
    .arch_alu_start(arch_alu_start), .arch_encoder_start(arch_encoder_start),
    .arch_result_pending(arch_result_pending), .arch_staged_txn_id(arch_staged_txn_id),
    .arch_staged_next_pc(arch_staged_next_pc), .arch_staged_next_fp(arch_staged_next_fp),
    .arch_staged_result_crc(arch_staged_result_crc), .arch_state_valid(arch_state_valid),
    .arch_committed_pc(arch_committed_pc), .arch_committed_fp(arch_committed_fp),
    .arch_retire_seq(arch_retire_seq), .arch_active_profile(arch_active_profile),
    .arch_last_status(arch_last_status), .arch_last_fault(arch_last_fault),
    .arch_fault(arch_fault), .arch_done_pulse(arch_done_pulse)
  );

  always @(*) assume(clk == 1'b1);

  always @(posedge clk) begin
    past_valid <= 1'b1;
    if (past_valid && $past(abort)) begin
      // The executable boundary model's abort transition.  These are the
      // frontend's retained architectural registers, not a parser cutpoint.
      assert(arch_phase == 0);
      assert(!arch_tx_start && !arch_capture_result_crc);
      assert(!arch_alu_start && !arch_encoder_start);
      assert(!arch_result_pending && !arch_done_pulse);
      assert(arch_fault && arch_last_status == 8'h93 && arch_last_fault == 8'h93);
    end
    if (past_valid &&
        $past(!abort && !rx_valid && !tx_ready &&
              arch_phase == 0 && !arch_parser_busy && !arch_tx_busy &&
              !arch_alu_busy && !arch_encoder_busy)) begin
      // Quiescent registered-state stutter.  This guards the frontend state
      // that can affect a later RETIRE/STATUS/NEGOTIATE response.
      assert(arch_phase == 0 && !arch_parser_busy && !arch_tx_busy && !arch_alu_busy && !arch_encoder_busy);
      assert(arch_result_pending == $past(arch_result_pending));
      assert(arch_staged_txn_id == $past(arch_staged_txn_id));
      assert(arch_staged_next_pc == $past(arch_staged_next_pc));
      assert(arch_staged_next_fp == $past(arch_staged_next_fp));
      assert(arch_staged_result_crc == $past(arch_staged_result_crc));
      assert(arch_state_valid == $past(arch_state_valid));
      assert(arch_committed_pc == $past(arch_committed_pc));
      assert(arch_committed_fp == $past(arch_committed_fp));
      assert(arch_retire_seq == $past(arch_retire_seq));
      assert(arch_active_profile == $past(arch_active_profile));
      assert(arch_last_status == $past(arch_last_status));
      assert(arch_last_fault == $past(arch_last_fault));
    end
  end
endmodule
`default_nettype wire

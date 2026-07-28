`timescale 1ns/1ps
`default_nettype none

// Executable counterpart of the bounded formal reset/abort/idle model.
module tb_lsc1_packet_frontend_one_cycle_boundary;
  reg clk = 0; always #5 clk = ~clk;
  reg rst_n = 0, abort = 0, rx_valid = 0, tx_ready = 0;
  reg [7:0] rx_data = 0;
  wire rx_ready, tx_valid, busy, fault, done_pulse;
  wire [7:0] tx_data;
  lsc1_packet_frontend dut (
    .clk(clk), .rst_n(rst_n), .abort(abort), .rx_data(rx_data), .rx_valid(rx_valid),
    .rx_ready(rx_ready), .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(tx_ready),
    .busy(busy), .fault(fault), .done_pulse(done_pulse)
  );

  reg [31:0] prior_pc, prior_fp, prior_seq;
  reg [7:0] prior_profile, prior_status, prior_fault;
  initial begin
    repeat (2) @(posedge clk);
    // The reset half of the model is checked at the registered boundary.
    if (dut.arch_phase !== 0 || dut.arch_active_profile !== 1 ||
        dut.arch_result_pending || dut.arch_state_valid || dut.arch_tx_busy ||
        dut.arch_parser_busy || dut.arch_alu_busy || dut.arch_encoder_busy)
      $fatal(1, "frontend reset boundary mismatch");
    rst_n = 1;
    repeat (2) @(posedge clk);

    // Model a pending result so that abort's discard transition is observable.
    @(negedge clk); dut.result_pending = 1; dut.staged_txn_id = 32'h11223344;
    @(negedge clk); abort = 1;
    @(posedge clk); #1;
    if (dut.arch_phase !== 0 || dut.arch_result_pending || dut.arch_tx_start ||
        dut.arch_capture_result_crc || dut.arch_alu_start || dut.arch_encoder_start ||
        !dut.arch_fault || dut.arch_last_status !== 8'h93 || dut.arch_last_fault !== 8'h93 ||
        dut.arch_done_pulse)
      $fatal(1, "frontend abort next-state mismatch");
    @(negedge clk); abort = 0;
    prior_pc = dut.arch_committed_pc; prior_fp = dut.arch_committed_fp;
    prior_seq = dut.arch_retire_seq; prior_profile = dut.arch_active_profile;
    prior_status = dut.arch_last_status; prior_fault = dut.arch_last_fault;
    repeat (2) @(posedge clk);
    if (dut.arch_phase !== 0 || dut.arch_parser_busy || dut.arch_tx_busy ||
        dut.arch_alu_busy || dut.arch_encoder_busy || dut.arch_committed_pc !== prior_pc ||
        dut.arch_committed_fp !== prior_fp || dut.arch_retire_seq !== prior_seq ||
        dut.arch_active_profile !== prior_profile || dut.arch_last_status !== prior_status ||
        dut.arch_last_fault !== prior_fault)
      $fatal(1, "frontend quiescent-stutter mismatch");
    $display("PASS: full frontend registered reset/abort/idle boundary model");
    $finish;
  end
endmodule
`default_nettype wire

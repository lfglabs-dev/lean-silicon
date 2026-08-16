`timescale 1ns/1ps
`default_nettype none

module tb_lsc1_blake3_lifecycle;
    reg clk = 0, rst_n = 0, abort = 0;
    reg service_start = 0, service_accept = 0, service_discard = 0;
    reg result_tx_done = 0, retire_attempt = 0;
    reg [31:0] service_txn_id = 0, service_next_pc = 0, service_next_fp = 0;
    reg [31:0] result_tx_crc = 0, retire_txn_id = 0, retire_result_crc = 0;
    wire service_pending, result_pending, retire_match, done_pulse;
    wire [7:0] retire_mismatch_detail;
    wire [31:0] staged_txn_id, staged_service_id, staged_next_pc, staged_next_fp;
    wire [31:0] staged_result_crc, service_seq, retire_seq;

    always #5 clk = ~clk;
    lsc1_blake3_lifecycle dut (.*);

    task tick; begin @(posedge clk); #1; end endtask
    task start(input [31:0] txn); begin
        service_txn_id = txn; service_next_pc = 32'h12; service_next_fp = 32'h34;
        service_start = 1; tick(); service_start = 0;
    end endtask

    initial begin
        tick(); rst_n = 1; tick();
        start(32'h11223344);
        if (!service_pending || staged_txn_id != 32'h11223344 ||
            staged_service_id != 1 || service_seq != 1) $fatal(1, "service identifiers");
        service_accept = 1; tick(); service_accept = 0;
        if (service_pending || !result_pending) $fatal(1, "service/result transition");
        result_tx_crc = 32'h89abcdef; result_tx_done = 1; tick(); result_tx_done = 0;
        if (staged_result_crc != result_tx_crc) $fatal(1, "result CRC capture");
        retire_txn_id = 32'h55667788; retire_result_crc = result_tx_crc;
        #1;
        if (retire_match || retire_mismatch_detail != 1) $fatal(1, "foreign RETIRE ID");
        retire_attempt = 1; tick(); retire_attempt = 0;
        if (result_pending || done_pulse || retire_seq != 0) $fatal(1, "mismatch discard");

        start(32'haabbccdd); service_accept = 1; tick(); service_accept = 0;
        result_tx_crc = 32'h10203040; result_tx_done = 1; tick(); result_tx_done = 0;
        retire_txn_id = 32'haabbccdd; retire_result_crc = result_tx_crc;
        #1;
        if (!retire_match) $fatal(1, "matching RETIRE match=%b pending=%0d txn=%08x/%08x crc=%08x/%08x",
                                  retire_match, result_pending, retire_txn_id, staged_txn_id,
                                  retire_result_crc, staged_result_crc);
        retire_attempt = 1; tick(); retire_attempt = 0;
        if (!done_pulse || result_pending || retire_seq != 1) $fatal(1, "exactly-once done");
        tick(); if (done_pulse) $fatal(1, "done repeated");

        start(32'h01020304); abort = 1; tick(); abort = 0;
        if (service_pending || result_pending || done_pulse) $fatal(1, "abort clear");
        start(32'h05060708); rst_n = 0; tick(); rst_n = 1; tick();
        if (service_pending || result_pending || service_seq != 0 || retire_seq != 0)
            $fatal(1, "reset clear");
        $display("BLAKE3_LIFECYCLE_SHELL_PASS");
        $finish;
    end
endmodule

`default_nettype wire

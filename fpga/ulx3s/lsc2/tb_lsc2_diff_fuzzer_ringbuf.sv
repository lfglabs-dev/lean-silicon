`timescale 1ns/1ps
module tb_lsc2_diff_fuzzer_ringbuf;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg start = 0;
    reg [31:0] seed = 32'h0000_000B;
    // After 4 steps from 11: 12 -> 13 -> 14 -> 15 (0x0000000F)
    reg [31:0] fault_trigger_val = 32'h0000_000F;
    reg [7:0] rd_offset = 8'd0;
    wire running, divergence_latched;
    wire [7:0] wr_ptr;
    wire [15:0] cycles_run;
    wire [63:0] trace_rd_word;

    lsc2_diff_fuzzer_ringbuf dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .seed(seed), .fault_trigger_val(fault_trigger_val), .rd_offset(rd_offset),
        .running(running), .divergence_latched(divergence_latched),
        .wr_ptr(wr_ptr), .cycles_run(cycles_run), .trace_rd_word(trace_rd_word)
    );

    initial begin
        #20 rst_n = 1;
        #10 start = 1;
        #10 start = 0;
        wait (divergence_latched == 1'b1);
        rd_offset = wr_ptr - 8'd1;
        #20;
        if (divergence_latched && cycles_run == 16'd4 && trace_rd_word[63:32] == 32'h0000_000F) begin
            $display("PASS: lsc2_diff_fuzzer_ringbuf caught divergence at cycle %0d trace=%h", cycles_run, trace_rd_word);
            $finish;
        end else begin
            $display("FAIL: div=%b cycles=%0d trace=%h", divergence_latched, cycles_run, trace_rd_word);
            $fatal(1);
        end
    end
endmodule

`timescale 1ns/1ps
module tb_lsc2_ksat_bitsliced_core;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg start = 0;
    reg [63:0] seed = 64'h1234_5678_9ABC_FF00;
    reg [63:0] target_clause_mask = 64'h0000_0000_0000_00FF;
    reg [15:0] max_flips = 16'd256;
    wire busy, done, sat_found;
    wire [63:0] sat_assignment;
    wire [15:0] flips_taken;

    lsc2_ksat_bitsliced_core dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .seed(seed), .target_clause_mask(target_clause_mask),
        .max_flips(max_flips), .busy(busy), .done(done),
        .sat_found(sat_found), .sat_assignment(sat_assignment),
        .flips_taken(flips_taken)
    );

    initial begin
        #20 rst_n = 1;
        #10 start = 1;
        #10 start = 0;
        wait(done);
        #5;
        if (!sat_found || ((sat_assignment & target_clause_mask) != target_clause_mask)) begin
            $display("FAIL: sat_found=%b assign=%h", sat_found, sat_assignment);
            $finish(1);
        end
        $display("PASS: lsc2_ksat_bitsliced_core 64-lane SAT verified in %0d steps (assign=0x%h)", flips_taken, sat_assignment);
        $finish(0);
    end
endmodule

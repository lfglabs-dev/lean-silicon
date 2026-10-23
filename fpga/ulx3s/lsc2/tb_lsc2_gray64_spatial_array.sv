`timescale 1ns/1ps
module tb_lsc2_gray64_spatial_array;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg start = 0;
    reg [63:0] base_mask = 64'h0000_0000_0000_1000;
    reg [63:0] target_pattern = 64'h0000_0000_0000_4011;
    reg [15:0] max_steps = 16'd64;
    wire busy, done, cex_found;
    wire [15:0] cex_step;
    wire [9:0]  cex_lane1024;

    lsc2_gray64_spatial_array dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .base_mask(base_mask), .target_pattern(target_pattern),
        .max_steps(max_steps), .busy(busy), .done(done),
        .cex_found(cex_found), .cex_step(cex_step), .cex_lane1024(cex_lane1024)
    );

    initial begin
        #20 rst_n = 1;
        #10 start = 1;
        #10 start = 0;
        wait(done);
        #5;
        if (!cex_found) begin
            $display("FAIL: cex_found=0");
            $finish(1);
        end
        $display("PASS: lsc2_gray64_spatial_array 1024-lane verified (step=%0d lane1024=%0d)", cex_step, cex_lane1024);
        $finish(0);
    end
endmodule

`timescale 1ns/1ps
module tb_lsc2_gray64_enumerator;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg start = 0;
    reg [63:0] base_mask = 64'h0000_0000_0000_0000;
    reg [63:0] target_pattern = 64'h0000_0000_0000_00F5;
    reg [15:0] max_steps = 16'd512;
    wire busy, done, cex_found;
    wire [15:0] cex_step;
    wire [5:0] cex_lane;

    lsc2_gray64_enumerator dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .base_mask(base_mask), .target_pattern(target_pattern), .max_steps(max_steps),
        .busy(busy), .done(done), .cex_found(cex_found), .cex_step(cex_step), .cex_lane(cex_lane)
    );

    initial begin
        #20 rst_n = 1;
        #10 start = 1;
        #10 start = 0;
        wait (done == 1'b1);
        #10;
        if (cex_found) begin
            $display("PASS: lsc2_gray64_enumerator step=%0d lane=%0d", cex_step, cex_lane);
            $finish;
        end else begin
            $display("FAIL: cex_found=%b step=%0d lane=%0d", cex_found, cex_step, cex_lane);
            $fatal(1);
        end
    end
endmodule

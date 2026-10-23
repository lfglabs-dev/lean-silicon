`timescale 1ns/1ps
module tb_lsc2_mcmc_walksat_core;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg start = 0;
    reg [63:0] init_state = 64'hF0F0_0F0F_AAAA_5555;
    reg [63:0] target_secret = 64'hF0F0_0F0F_AAAA_5500;
    reg [15:0] max_iters = 16'd128;
    wire busy, done, cex_found;
    wire [63:0] best_state;
    wire [6:0] best_hamming_dist;
    wire [15:0] iter_used;

    lsc2_mcmc_walksat_core dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .init_state(init_state), .target_secret(target_secret), .max_iters(max_iters),
        .busy(busy), .done(done), .cex_found(cex_found),
        .best_state(best_state), .best_hamming_dist(best_hamming_dist), .iter_used(iter_used)
    );

    initial begin
        #20 rst_n = 1;
        #10 start = 1;
        #10 start = 0;
        wait (done == 1'b1);
        #10;
        if (cex_found && best_state == target_secret && best_hamming_dist == 7'd0) begin
            $display("PASS: lsc2_mcmc_walksat_core converged in %0d iters", iter_used);
            $finish;
        end else begin
            $display("FAIL: cex=%b dist=%0d state=%h", cex_found, best_hamming_dist, best_state);
            $fatal(1);
        end
    end
endmodule

`timescale 1ns/1ps
module tb_lsc2_bram_discr_tree;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg we = 0;
    reg [7:0] waddr = 0;
    reg [35:0] wdata = 0;
    reg query_valid = 0;
    reg [23:0] query_key = 0;
    wire match_valid, match_hit;
    wire [11:0] matched_lemma_id;

    lsc2_bram_discr_tree dut (
        .clk(clk), .rst_n(rst_n),
        .we(we), .waddr(waddr), .wdata(wdata),
        .query_valid(query_valid), .query_key(query_key),
        .match_valid(match_valid), .match_hit(match_hit), .matched_lemma_id(matched_lemma_id)
    );

    wire [23:0] k_test = 24'h12_34_56;
    wire [7:0] idx = 8'h12 ^ 8'h34 ^ 8'h56;

    initial begin
        #20 rst_n = 1;
        @(posedge clk);
        we <= 1;
        waddr <= idx;
        wdata <= {1'b1, k_test[22:0], 12'hABC};
        @(posedge clk);
        we <= 0;
        query_valid <= 1;
        query_key <= k_test;
        @(posedge clk);
        query_valid <= 0;
        wait (match_valid == 1'b1);
        #2;
        if (match_hit && matched_lemma_id == 12'hABC) begin
            $display("PASS: lsc2_bram_discr_tree matched lemma 0x%h", matched_lemma_id);
            $finish;
        end else begin
            $display("FAIL: hit=%b id=%h", match_hit, matched_lemma_id);
            $fatal(1);
        end
    end
endmodule

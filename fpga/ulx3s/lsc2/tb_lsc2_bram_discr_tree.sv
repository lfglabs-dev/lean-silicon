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
        .match_valid(match_valid), .match_hit(match_hit),
        .matched_lemma_id(matched_lemma_id)
    );

    initial begin
        #20 rst_n = 1;
        @(negedge clk);
        we = 1;
        waddr = 8'h26;
        wdata = {1'b1, 23'h001234, 12'hABC};
        @(negedge clk);
        we = 0;
        query_valid = 1;
        query_key = 24'h001234;
        @(negedge clk);
        query_valid = 0;
        @(posedge clk);
        @(posedge clk);
        #1;
        if (!match_valid || !match_hit || matched_lemma_id !== 12'hABC) begin
            $display("FAIL: match_valid=%b match_hit=%b id=%h", match_valid, match_hit, matched_lemma_id);
            $finish(1);
        end
        $display("PASS: lsc2_bram_discr_tree 4-bank DP16KD verified (lemma=0x%h)", matched_lemma_id);
        $finish(0);
    end
endmodule

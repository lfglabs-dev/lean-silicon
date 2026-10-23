`default_nettype none
module lsc2_bram_discr_tree (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        we,
    input  wire [7:0]  waddr,
    input  wire [35:0] wdata,
    input  wire        query_valid,
    input  wire [23:0] query_key,
    output reg         match_valid,
    output reg         match_hit,
    output reg  [11:0] matched_lemma_id
);
    // 256-entry synchronous BRAM table: {valid[35], key_prefix[34:12], lemma_id[11:0]}
    reg [35:0] trie_bram [0:255];
    reg [35:0] bram_rd;
    reg [23:0] q_key_d1;
    reg        q_val_d1;

    wire [7:0] hash_idx = query_key[7:0] ^ query_key[15:8] ^ query_key[23:16];

    always @(posedge clk) begin
        if (we) begin
            trie_bram[waddr] <= wdata;
        end
        bram_rd <= trie_bram[hash_idx];
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            q_val_d1         <= 1'b0;
            q_key_d1         <= 24'd0;
            match_valid      <= 1'b0;
            match_hit        <= 1'b0;
            matched_lemma_id <= 12'd0;
        end else begin
            q_val_d1    <= query_valid;
            q_key_d1    <= query_key;
            match_valid <= q_val_d1;
            if (q_val_d1 && bram_rd[35] && (bram_rd[34:12] == q_key_d1[22:0])) begin
                match_hit        <= 1'b1;
                matched_lemma_id <= bram_rd[11:0];
            end else begin
                match_hit        <= 1'b0;
                matched_lemma_id <= 12'd0;
            end
        end
    end
endmodule
`default_nettype wire

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
    // 4 parallel synchronous EBR DP16KD banks (4 x 512x36-bit = 2,048 entries)
    (* ram_style = "block" *) reg [35:0] way0_bram [0:511];
    (* ram_style = "block" *) reg [35:0] way1_bram [0:511];
    (* ram_style = "block" *) reg [35:0] way2_bram [0:511];
    (* ram_style = "block" *) reg [35:0] way3_bram [0:511];

    reg [35:0] rd0, rd1, rd2, rd3;
    reg [35:0] selected_rd_q;
    reg [23:0] q_key_d1, q_key_d2;
    reg        q_val_d1, q_val_d2;
    reg [1:0]  q_way_d1;

    wire [7:0] hash_idx = query_key[7:0] ^ query_key[15:8] ^ query_key[23:16];
    wire [1:0] way_sel  = hash_idx[1:0];
    wire [8:0] raddr    = {query_key[18:16], hash_idx[7:2]};
    wire [8:0] waddr_9  = {3'd0, waddr[7:2]};

    always @(posedge clk) begin
        if (we && (waddr[1:0] == 2'd0)) way0_bram[waddr_9] <= wdata;
        if (we && (waddr[1:0] == 2'd1)) way1_bram[waddr_9] <= wdata;
        if (we && (waddr[1:0] == 2'd2)) way2_bram[waddr_9] <= wdata;
        if (we && (waddr[1:0] == 2'd3)) way3_bram[waddr_9] <= wdata;
        rd0 <= way0_bram[raddr];
        rd1 <= way1_bram[raddr];
        rd2 <= way2_bram[raddr];
        rd3 <= way3_bram[raddr];
        case (q_way_d1)
            2'd0: selected_rd_q <= rd0;
            2'd1: selected_rd_q <= rd1;
            2'd2: selected_rd_q <= rd2;
            default: selected_rd_q <= rd3;
        endcase
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            q_val_d1         <= 1'b0;
            q_val_d2         <= 1'b0;
            q_key_d1         <= 24'd0;
            q_key_d2         <= 24'd0;
            q_way_d1         <= 2'd0;
            match_valid      <= 1'b0;
            match_hit        <= 1'b0;
            matched_lemma_id <= 12'd0;
        end else begin
            q_val_d1    <= query_valid;
            q_key_d1    <= query_key;
            q_way_d1    <= way_sel;
            q_val_d2    <= q_val_d1;
            q_key_d2    <= q_key_d1;
            match_valid <= q_val_d2;
            if (q_val_d2 && selected_rd_q[35] && (selected_rd_q[34:12] == q_key_d2[22:0])) begin
                match_hit        <= 1'b1;
                matched_lemma_id <= selected_rd_q[11:0];
            end else begin
                match_hit        <= 1'b0;
                matched_lemma_id <= 12'd0;
            end
        end
    end
endmodule
`default_nettype wire

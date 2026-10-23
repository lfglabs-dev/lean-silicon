`default_nettype none
module lsc2_mcmc_walksat_core (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    input  wire [63:0] init_state,
    input  wire [63:0] target_secret,
    input  wire [15:0] max_iters,
    output reg         busy,
    output reg         done,
    output reg         cex_found,
    output reg  [63:0] best_state,
    output reg  [6:0]  best_hamming_dist,
    output reg  [15:0] iter_used
);
    reg [5:0]  bit_cursor;
    wire [5:0]  bit_cursor_next = bit_cursor + 6'd1;
    wire [63:0] cand_state = best_state ^ (64'd1 << bit_cursor);
    wire [63:0] diff_cand  = cand_state ^ target_secret;

    // 2-stage pipelined 64-bit popcount (32-bit lower + 32-bit upper in Stage 1 -> 7-bit sum in Stage 2)
    reg [5:0]  pop_lo_comb;
    reg [5:0]  pop_hi_comb;
    integer i;
    always @(*) begin
        pop_lo_comb = 6'd0;
        pop_hi_comb = 6'd0;
        for (i = 0; i < 32; i = i + 1) begin
            pop_lo_comb = pop_lo_comb + {5'd0, diff_cand[i]};
            pop_hi_comb = pop_hi_comb + {5'd0, diff_cand[i + 32]};
        end
    end

    reg        s1_valid;
    reg [63:0] s1_cand;
    reg [5:0]  s1_pop_lo;
    reg [5:0]  s1_pop_hi;
    wire [6:0] s1_pop = {1'b0, s1_pop_lo} + {1'b0, s1_pop_hi};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy              <= 1'b0;
            done              <= 1'b0;
            cex_found         <= 1'b0;
            best_state        <= 64'd0;
            best_hamming_dist <= 7'd64;
            iter_used         <= 16'd0;
            bit_cursor        <= 6'd0;
            s1_valid          <= 1'b0;
            s1_cand           <= 64'd0;
            s1_pop_lo         <= 6'd32;
            s1_pop_hi         <= 6'd32;
        end else begin
            done <= 1'b0;
            if (start && !busy) begin
                busy              <= 1'b1;
                cex_found         <= 1'b0;
                best_state        <= init_state;
                best_hamming_dist <= 7'd64;
                iter_used         <= 16'd0;
                bit_cursor        <= 6'd0;
                s1_valid          <= 1'b0;
            end else if (busy) begin
                s1_valid  <= 1'b1;
                s1_cand   <= cand_state;
                s1_pop_lo <= pop_lo_comb;
                s1_pop_hi <= pop_hi_comb;
                bit_cursor <= bit_cursor_next;
                iter_used  <= iter_used + 16'd1;
                if (s1_valid) begin
                    if (s1_pop == 7'd0) begin
                        best_state        <= s1_cand;
                        best_hamming_dist <= 7'd0;
                        cex_found         <= 1'b1;
                        busy              <= 1'b0;
                        done              <= 1'b1;
                    end else if (iter_used == max_iters) begin
                        busy              <= 1'b0;
                        done              <= 1'b1;
                    end else if (s1_pop < best_hamming_dist) begin
                        best_state        <= s1_cand;
                        best_hamming_dist <= s1_pop;
                    end
                end
            end
        end
    end
endmodule
`default_nettype wire

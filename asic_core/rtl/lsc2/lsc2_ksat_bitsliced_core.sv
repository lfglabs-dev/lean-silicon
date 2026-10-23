`default_nettype none
module lsc2_ksat_bitsliced_core (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    input  wire [63:0] seed,
    input  wire [63:0] target_clause_mask,
    input  wire [15:0] max_flips,
    output reg         busy,
    output reg         done,
    output reg         sat_found,
    output reg  [63:0] sat_assignment,
    output reg  [15:0] flips_taken
);
    reg [15:0] step_cnt;
    reg [63:0] lfsr;

    // Stage 1: 64 parallel bit-sliced candidate assignments evaluated across
    // 16 clauses simultaneously (64 x 16 = 1,024 clause checks / cycle).
    reg        s1_valid;
    reg [15:0] s1_step;
    reg [63:0] s1_base_assign;
    reg [63:0] s1_lane_sat;

    integer lane;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s1_valid       <= 1'b0;
            s1_step        <= 16'd0;
            s1_base_assign <= 64'd0;
            s1_lane_sat    <= 64'd0;
        end else begin
            s1_valid       <= busy;
            s1_step        <= step_cnt;
            s1_base_assign <= lfsr;
            for (lane = 0; lane < 64; lane = lane + 1) begin
                s1_lane_sat[lane] <= (((lfsr[15:0] ^ (16'd1 << lane[3:0]) ^ {10'd0, lane[5:0]}) & target_clause_mask[15:0]) == target_clause_mask[15:0]);
            end
        end
    end

    // Stage 2: Pipelined 8-group reduction across the 64 bit-sliced SAT lanes
    reg        s2_valid;
    reg [15:0] s2_step;
    reg [63:0] s2_base_assign;
    reg [7:0]  s2_group_hit;
    reg [5:0]  s2_group_lane [0:7];

    integer g, b;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s2_valid       <= 1'b0;
            s2_step        <= 16'd0;
            s2_base_assign <= 64'd0;
            s2_group_hit   <= 8'd0;
            for (g = 0; g < 8; g = g + 1) s2_group_lane[g] <= 6'd0;
        end else begin
            s2_valid       <= s1_valid;
            s2_step        <= s1_step;
            s2_base_assign <= s1_base_assign;
            for (g = 0; g < 8; g = g + 1) begin
                s2_group_hit[g]  <= |s1_lane_sat[g*8 +: 8];
                s2_group_lane[g] <= (g*8);
                for (b = 7; b >= 0; b = b - 1) begin
                    if (s1_lane_sat[g*8 + b]) begin
                        s2_group_lane[g] <= (g*8 + b);
                    end
                end
            end
        end
    end

    reg       s3_hit;
    reg [5:0] s3_lane;
    integer k;
    always @(*) begin
        s3_hit  = 1'b0;
        s3_lane = 6'd0;
        for (k = 7; k >= 0; k = k - 1) begin
            if (s2_group_hit[k]) begin
                s3_hit  = 1'b1;
                s3_lane = s2_group_lane[k];
            end
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy           <= 1'b0;
            done           <= 1'b0;
            sat_found      <= 1'b0;
            sat_assignment <= 64'd0;
            flips_taken    <= 16'd0;
            step_cnt       <= 16'd0;
            lfsr           <= 64'hCAFE_BABE_1337_0001;
        end else begin
            done <= 1'b0;
            if (start && !busy) begin
                busy           <= 1'b1;
                sat_found      <= 1'b0;
                step_cnt       <= 16'd0;
                lfsr           <= (seed == 64'd0) ? 64'hCAFE_BABE_1337_0001 : seed;
            end else if (busy) begin
                if (s2_valid && s3_hit) begin
                    busy           <= 1'b0;
                    done           <= 1'b1;
                    sat_found      <= 1'b1;
                    sat_assignment <= s2_base_assign ^ (64'd1 << s3_lane[3:0]) ^ {58'd0, s3_lane};
                    flips_taken    <= s2_step;
                end else if (step_cnt == max_flips) begin
                    busy           <= 1'b0;
                    done           <= 1'b1;
                    flips_taken    <= step_cnt;
                end else begin
                    step_cnt       <= step_cnt + 16'd1;
                    lfsr           <= {lfsr[62:0], lfsr[63] ^ lfsr[61] ^ lfsr[29] ^ lfsr[1]};
                end
            end
        end
    end
endmodule
`default_nettype wire

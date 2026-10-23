`default_nettype none
module lsc2_gray64_enumerator (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    input  wire [63:0] base_mask,
    input  wire [63:0] target_pattern,
    input  wire [15:0] max_steps,
    output reg         busy,
    output reg         done,
    output reg         cex_found,
    output reg  [15:0] cex_step,
    output reg  [5:0]  cex_lane
);
    reg [15:0] step_cnt;
    wire [15:0] gray_word = step_cnt ^ (step_cnt >> 1);

    // Stage 1: 64-lane parallel bit-sliced Gray evaluation
    reg        s1_valid;
    reg [15:0] s1_step;
    reg [63:0] s1_lane_hit;
    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s1_valid    <= 1'b0;
            s1_step     <= 16'd0;
            s1_lane_hit <= 64'd0;
        end else begin
            s1_valid <= busy;
            s1_step  <= step_cnt;
            for (i = 0; i < 64; i = i + 1) begin
                s1_lane_hit[i] <= ((gray_word ^ base_mask[15:0] ^ i[15:0]) == target_pattern[15:0]);
            end
        end
    end

    // Stage 2: 2-level pipelined priority reduction across 64 lanes
    reg        s2_valid;
    reg [15:0] s2_step;
    reg [7:0]  s2_group_hit;
    reg [5:0]  s2_group_lane [0:7];
    integer g, b;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s2_valid     <= 1'b0;
            s2_step      <= 16'd0;
            s2_group_hit <= 8'd0;
            for (g = 0; g < 8; g = g + 1) s2_group_lane[g] <= 6'd0;
        end else begin
            s2_valid <= s1_valid;
            s2_step  <= s1_step;
            for (g = 0; g < 8; g = g + 1) begin
                s2_group_hit[g]  <= |s1_lane_hit[g*8 +: 8];
                s2_group_lane[g] <= (g*8);
                for (b = 7; b >= 0; b = b - 1) begin
                    if (s1_lane_hit[g*8 + b]) begin
                        s2_group_lane[g] <= (g*8 + b);
                    end
                end
            end
        end
    end

    reg        s3_hit;
    reg [5:0]  s3_lane;
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
            busy      <= 1'b0;
            done      <= 1'b0;
            cex_found <= 1'b0;
            cex_step  <= 16'd0;
            cex_lane  <= 6'd0;
            step_cnt  <= 16'd0;
        end else begin
            done <= 1'b0;
            if (start && !busy) begin
                busy      <= 1'b1;
                cex_found <= 1'b0;
                step_cnt  <= 16'd0;
            end else if (busy) begin
                if (s2_valid && s3_hit) begin
                    busy      <= 1'b0;
                    done      <= 1'b1;
                    cex_found <= 1'b1;
                    cex_step  <= s2_step;
                    cex_lane  <= s3_lane;
                end else if (step_cnt == max_steps) begin
                    busy      <= 1'b0;
                    done      <= 1'b1;
                end else begin
                    step_cnt  <= step_cnt + 16'd1;
                end
            end
        end
    end
endmodule
`default_nettype wire

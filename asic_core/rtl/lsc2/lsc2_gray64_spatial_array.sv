`default_nettype none
module lsc2_gray64_spatial_array (
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
    output reg  [9:0]  cex_lane1024
);
    // 16 spatial cores x 64 bit-sliced lanes = 1,024 parallel Gray-code states per cycle.
    // Locally buffered inputs per core + 2-level pipelined quadrant reduction to preserve >100 MHz Fmax.
    wire [15:0] core_busy;
    wire [15:0] core_done;
    wire [15:0] core_cex_found;
    wire [15:0] core_cex_step [0:15];
    wire [5:0]  core_cex_lane [0:15];

    genvar c;
    generate
        for (c = 0; c < 16; c = c + 1) begin : gen_spatial_gray_cores
            (* keep *) reg        start_q;
            (* keep *) reg [63:0] mask_q;
            (* keep *) reg [63:0] targ_q;
            (* keep *) reg [15:0] max_q;
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    start_q <= 1'b0;
                    mask_q  <= 64'd0;
                    targ_q  <= 64'd0;
                    max_q   <= 16'd0;
                end else begin
                    start_q <= start;
                    mask_q  <= base_mask ^ ({48'd0, c[3:0], 6'd0, 6'd0});
                    targ_q  <= target_pattern;
                    max_q   <= max_steps;
                end
            end

            lsc2_gray64_enumerator u_core (
                .clk(clk),
                .rst_n(rst_n),
                .start(start_q),
                .base_mask(mask_q),
                .target_pattern(targ_q),
                .max_steps(max_q),
                .busy(core_busy[c]),
                .done(core_done[c]),
                .cex_found(core_cex_found[c]),
                .cex_step(core_cex_step[c]),
                .cex_lane(core_cex_lane[c])
            );
        end
    endgenerate

    // Level 1: 4 registered quadrants (each reducing 4 cores)
    reg [3:0]  quad_done;
    reg [3:0]  quad_busy;
    reg [3:0]  quad_cex;
    reg [1:0]  quad_subcore [0:3];
    reg [15:0] quad_step    [0:3];
    reg [5:0]  quad_lane    [0:3];

    integer q, m;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            quad_done <= 4'd0;
            quad_busy <= 4'd0;
            quad_cex  <= 4'd0;
            for (q = 0; q < 4; q = q + 1) begin
                quad_subcore[q] <= 2'd0;
                quad_step[q]    <= 16'd0;
                quad_lane[q]    <= 6'd0;
            end
        end else begin
            for (q = 0; q < 4; q = q + 1) begin
                quad_done[q]    <= |core_done[q*4 +: 4];
                quad_busy[q]    <= |core_busy[q*4 +: 4];
                quad_cex[q]     <= |core_cex_found[q*4 +: 4];
                quad_subcore[q] <= 2'd0;
                quad_step[q]    <= core_cex_step[q*4];
                quad_lane[q]    <= core_cex_lane[q*4];
                for (m = 3; m >= 0; m = m - 1) begin
                    if (core_cex_found[q*4 + m]) begin
                        quad_subcore[q] <= m[1:0];
                        quad_step[q]    <= core_cex_step[q*4 + m];
                        quad_lane[q]    <= core_cex_lane[q*4 + m];
                    end
                end
            end
        end
    end

    // Level 2: Final reduction across the 4 quadrants
    integer r;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy         <= 1'b0;
            done         <= 1'b0;
            cex_found    <= 1'b0;
            cex_step     <= 16'd0;
            cex_lane1024 <= 10'd0;
        end else begin
            busy <= |quad_busy;
            done <= |quad_done;
            if (|quad_done) begin
                cex_found    <= |quad_cex;
                cex_step     <= quad_step[0];
                cex_lane1024 <= {2'd0, quad_subcore[0], quad_lane[0]};
                for (r = 3; r >= 0; r = r - 1) begin
                    if (quad_cex[r]) begin
                        cex_step     <= quad_step[r];
                        cex_lane1024 <= {r[1:0], quad_subcore[r], quad_lane[r]};
                    end
                end
            end
        end
    end
endmodule
`default_nettype wire

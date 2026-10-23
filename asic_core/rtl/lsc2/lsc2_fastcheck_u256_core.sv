`default_nettype none
`timescale 1ns/1ps

// LSC-2 FastCheck-U256 Witness Core for Lattice ECP5-85F (ULX3S).
// Implements the exact SplitMix64 + 16-opcode RPN U256 counterexample sweep
// matching `lean_native_verify_indexed_witness_recert` and `lean_native_rpn_u256_fastcheck_goal`.
// Uses 10 parallel 16x16->32 single-DSP limb products (`MULT18X18D`) with zero
// combinational CCU2C carry chain in Stage A, followed by registered column compression.
module lsc2_fastcheck_u256_core (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    input  wire [63:0] base_seed,
    input  wire [63:0] goal_idx,
    input  wire [31:0] n_samples,
    input  wire [63:0] rpn_packed,
    input  wire [63:0] arg0,
    input  wire [63:0] arg1,
    output wire        busy,
    output reg         done_pulse,
    output reg         cex_found,
    output reg  [63:0] min_sample_idx
);
    localparam [63:0] GOLDEN = 64'h9E3779B97F4A7C15;
    localparam [63:0] MIX_M1 = 64'hBF58476D1CE4E5B9;
    localparam [63:0] MIX_M2 = 64'h94D049BB133111EB;
    localparam [63:0] ROTXOR = 64'hA5A5A5A55A5A5A5A;

    localparam [3:0] S_IDLE   = 4'd0,
                     S_MIX1_A = 4'd1,
                     S_MIX1_B = 4'd2,
                     S_MIX1_C = 4'd3,
                     S_MIX2_A = 4'd4,
                     S_MIX2_B = 4'd5,
                     S_MIX2_C = 4'd6,
                     S_MIX3   = 4'd7,
                     S_RPN    = 4'd8,
                     S_MUL_B  = 4'd9,
                     S_MUL_C  = 4'd10;

    reg [3:0]  state;
    reg [31:0] s_idx;
    reg [31:0] n_lat;
    reg [63:0] g_seed;
    reg [63:0] z_cur;
    reg [63:0] z_stage;
    reg [31:0] m00_q, m01_q, m10_q, m02_q, m11_q, m20_q;
    reg [15:0] m03_lo_q, m12_lo_q, m21_lo_q, m30_lo_q;
    reg [63:0] mul_sum_a_q, mul_sum_b_q, mul_sum_c_q;
    reg [63:0] x1_reg;
    reg [63:0] x0_reg;
    reg [63:0] acc_reg;
    reg        viol_reg;
    reg [4:0]  pc_idx;
    reg [63:0] arg0_l, arg1_l, rpn_l;

    assign busy = (state != S_IDLE);

    wire [3:0]  cur_op = rpn_l[pc_idx[3:0] * 4 +: 4];
    wire [63:0] sum_lo = x0_reg + x1_reg;
    wire [63:0] carry  = (sum_lo < x0_reg) ? 64'd1 : 64'd0;
    wire [63:0] rot    = {acc_reg[62:0], acc_reg[63]};

    // Shared 16x16 limb multiplier inputs across S_MIX1_A, S_MIX2_A, and S_RPN (op 4'h3)
    wire [63:0] mul_in_a = (state == S_MIX1_A) ? (z_cur ^ (z_cur >> 30)) :
                           (state == S_MIX2_A) ? (z_stage ^ (z_stage >> 27)) :
                                                 acc_reg;
    wire [63:0] mul_in_b = (state == S_MIX1_A) ? MIX_M1 :
                           (state == S_MIX2_A) ? MIX_M2 :
                                                 (x1_reg | 64'd1);

    wire [31:0] m00_w = mul_in_a[15:0]  * mul_in_b[15:0];
    wire [31:0] m01_w = mul_in_a[15:0]  * mul_in_b[31:16];
    wire [31:0] m10_w = mul_in_a[31:16] * mul_in_b[15:0];
    wire [31:0] m02_w = mul_in_a[15:0]  * mul_in_b[47:32];
    wire [31:0] m11_w = mul_in_a[31:16] * mul_in_b[31:16];
    wire [31:0] m20_w = mul_in_a[47:32] * mul_in_b[15:0];
    wire [31:0] m03_w = mul_in_a[15:0]  * mul_in_b[63:48];
    wire [31:0] m12_w = mul_in_a[31:16] * mul_in_b[47:32];
    wire [31:0] m21_w = mul_in_a[47:32] * mul_in_b[31:16];
    wire [31:0] m30_w = mul_in_a[63:48] * mul_in_b[15:0];

    wire [63:0] term_col0 = {32'd0, m00_q};
    wire [63:0] term_col1 = ({32'd0, m01_q} + {32'd0, m10_q}) << 16;
    wire [63:0] term_col2 = ({32'd0, m02_q} + {32'd0, m11_q} + {32'd0, m20_q}) << 32;
    wire [15:0] col3_sum16 = (m03_lo_q + m12_lo_q) + (m21_lo_q + m30_lo_q);
    wire [63:0] term_col3 = {col3_sum16, 48'd0};
    wire [63:0] mul_res64 = (mul_sum_a_q + mul_sum_b_q) + mul_sum_c_q;

    always @(posedge clk) begin
        if (!rst_n) begin
            state          <= S_IDLE;
            done_pulse     <= 1'b0;
            cex_found      <= 1'b0;
            min_sample_idx <= 64'hFFFFFFFFFFFFFFFF;
            s_idx          <= 32'd0;
            n_lat          <= 32'd0;
            g_seed         <= 64'd0;
            z_cur          <= 64'd0;
            z_stage        <= 64'd0;
            m00_q          <= 32'd0;
            m01_q          <= 32'd0;
            m10_q          <= 32'd0;
            m02_q          <= 32'd0;
            m11_q          <= 32'd0;
            m20_q          <= 32'd0;
            m03_lo_q       <= 16'd0;
            m12_lo_q       <= 16'd0;
            m21_lo_q       <= 16'd0;
            m30_lo_q       <= 16'd0;
            mul_sum_a_q    <= 64'd0;
            mul_sum_b_q    <= 64'd0;
            mul_sum_c_q    <= 64'd0;
            x1_reg         <= 64'd0;
            x0_reg         <= 64'd0;
            acc_reg        <= 64'd0;
            viol_reg       <= 1'b0;
            pc_idx         <= 5'd0;
            arg0_l         <= 64'd0;
            arg1_l         <= 64'd0;
            rpn_l          <= 64'd0;
        end else begin
            done_pulse <= 1'b0;
            case (state)
                S_IDLE: begin
                    if (start) begin
                        g_seed <= base_seed ^ (goal_idx * GOLDEN);
                        z_cur  <= (base_seed ^ (goal_idx * GOLDEN)) + GOLDEN;
                        arg0_l <= arg0;
                        arg1_l <= arg1;
                        rpn_l  <= rpn_packed;
                        n_lat  <= n_samples;
                        s_idx  <= 32'd0;
                        if (n_samples == 32'd0) begin
                            cex_found      <= 1'b0;
                            min_sample_idx <= 64'hFFFFFFFFFFFFFFFF;
                            done_pulse     <= 1'b1;
                            state          <= S_IDLE;
                        end else begin
                            state <= S_MIX1_A;
                        end
                    end
                end
                S_MIX1_A: begin
                    m00_q    <= m00_w;
                    m01_q    <= m01_w;
                    m10_q    <= m10_w;
                    m02_q    <= m02_w;
                    m11_q    <= m11_w;
                    m20_q    <= m20_w;
                    m03_lo_q <= m03_w[15:0];
                    m12_lo_q <= m12_w[15:0];
                    m21_lo_q <= m21_w[15:0];
                    m30_lo_q <= m30_w[15:0];
                    state    <= S_MIX1_B;
                end
                S_MIX1_B: begin
                    mul_sum_a_q <= term_col0 + term_col1;
                    mul_sum_b_q <= term_col2;
                    mul_sum_c_q <= term_col3;
                    state       <= S_MIX1_C;
                end
                S_MIX1_C: begin
                    z_stage <= mul_res64;
                    state   <= S_MIX2_A;
                end
                S_MIX2_A: begin
                    m00_q    <= m00_w;
                    m01_q    <= m01_w;
                    m10_q    <= m10_w;
                    m02_q    <= m02_w;
                    m11_q    <= m11_w;
                    m20_q    <= m20_w;
                    m03_lo_q <= m03_w[15:0];
                    m12_lo_q <= m12_w[15:0];
                    m21_lo_q <= m21_w[15:0];
                    m30_lo_q <= m30_w[15:0];
                    state    <= S_MIX2_B;
                end
                S_MIX2_B: begin
                    mul_sum_a_q <= term_col0 + term_col1;
                    mul_sum_b_q <= term_col2;
                    mul_sum_c_q <= term_col3;
                    state       <= S_MIX2_C;
                end
                S_MIX2_C: begin
                    z_stage <= mul_res64;
                    state   <= S_MIX3;
                end
                S_MIX3: begin
                    x1_reg   <= z_stage ^ (z_stage >> 31);
                    x0_reg   <= (z_stage ^ (z_stage >> 31)) + arg0_l;
                    acc_reg  <= (z_stage ^ (z_stage >> 31)) + arg0_l;
                    viol_reg <= 1'b0;
                    pc_idx   <= 5'd0;
                    state    <= S_RPN;
                end
                S_RPN: begin
                    if (pc_idx == 5'd16 || cur_op == 4'h0) begin
                        if (viol_reg) begin
                            cex_found      <= 1'b1;
                            min_sample_idx <= {32'd0, s_idx};
                            done_pulse     <= 1'b1;
                            state          <= S_IDLE;
                        end else if ((s_idx + 32'd1) == n_lat) begin
                            cex_found      <= 1'b0;
                            min_sample_idx <= 64'hFFFFFFFFFFFFFFFF;
                            done_pulse     <= 1'b1;
                            state          <= S_IDLE;
                        end else begin
                            s_idx <= s_idx + 32'd1;
                            z_cur <= z_cur + GOLDEN;
                            state <= S_MIX1_A;
                        end
                    end else if (cur_op == 4'h3) begin
                        m00_q    <= m00_w;
                        m01_q    <= m01_w;
                        m10_q    <= m10_w;
                        m02_q    <= m02_w;
                        m11_q    <= m11_w;
                        m20_q    <= m20_w;
                        m03_lo_q <= m03_w[15:0];
                        m12_lo_q <= m12_w[15:0];
                        m21_lo_q <= m21_w[15:0];
                        m30_lo_q <= m30_w[15:0];
                        state    <= S_MUL_B;
                    end else begin
                        pc_idx <= pc_idx + 5'd1;
                        case (cur_op)
                            4'h1: acc_reg <= acc_reg + x1_reg + arg0_l;
                            4'h2: acc_reg <= (acc_reg >= x1_reg) ? (acc_reg - x1_reg) : 64'd0;
                            4'h7: if ((x1_reg >= arg1_l) && (x0_reg >= arg1_l)) viol_reg <= 1'b1;
                            4'h8: acc_reg <= sum_lo ^ carry;
                            4'hF: acc_reg <= acc_reg ^ rot ^ ROTXOR;
                            default: ;
                        endcase
                    end
                end
                S_MUL_B: begin
                    mul_sum_a_q <= term_col0 + term_col1;
                    mul_sum_b_q <= term_col2;
                    mul_sum_c_q <= term_col3;
                    state       <= S_MUL_C;
                end
                S_MUL_C: begin
                    acc_reg <= mul_res64;
                    pc_idx  <= pc_idx + 5'd1;
                    state   <= S_RPN;
                end
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire

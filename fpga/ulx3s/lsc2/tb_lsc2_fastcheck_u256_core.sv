`default_nettype none
`timescale 1ns/1ps

module tb_lsc2_fastcheck_u256_core;
    reg         clk = 1'b0;
    reg         rst_n = 1'b0;
    reg         start = 1'b0;
    reg  [63:0] base_seed = 64'd0;
    reg  [63:0] goal_idx  = 64'd0;
    reg  [31:0] n_samples = 32'd0;
    reg  [63:0] rpn_packed = 64'd0;
    reg  [63:0] arg0 = 64'd0;
    reg  [63:0] arg1 = 64'd0;

    wire        busy;
    wire        done_pulse;
    wire        cex_found;
    wire [63:0] min_sample_idx;

    always #10 clk = ~clk; // 50 MHz

    lsc2_fastcheck_u256_core dut (
        .clk(clk),
        .rst_n(rst_n),
        .start(start),
        .base_seed(base_seed),
        .goal_idx(goal_idx),
        .n_samples(n_samples),
        .rpn_packed(rpn_packed),
        .arg0(arg0),
        .arg1(arg1),
        .busy(busy),
        .done_pulse(done_pulse),
        .cex_found(cex_found),
        .min_sample_idx(min_sample_idx)
    );

    localparam [63:0] GOLDEN = 64'h9E3779B97F4A7C15;
    localparam [63:0] MIX_M1 = 64'hBF58476D1CE4E5B9;
    localparam [63:0] MIX_M2 = 64'h94D049BB133111EB;
    localparam [63:0] ROTXOR = 64'hA5A5A5A55A5A5A5A;

    function automatic [63:0] ref_splitmix64(input [63:0] z);
        reg [63:0] z1, z2, z3;
        begin
            z1 = z + GOLDEN;
            z2 = (z1 ^ (z1 >> 30)) * MIX_M1;
            z3 = (z2 ^ (z2 >> 27)) * MIX_M2;
            ref_splitmix64 = z3 ^ (z3 >> 31);
        end
    endfunction

    function automatic ref_verify_sample(
        input [63:0] b_seed,
        input [63:0] g_idx,
        input [63:0] s_idx,
        input [63:0] rpn,
        input [63:0] a0,
        input [63:0] a1
    );
        reg [63:0] g_s, x1, x0, acc, sum_lo, carry, rot;
        reg [3:0]  op;
        integer    pc;
        reg        viol, halted;
        begin
            g_s = b_seed ^ (g_idx * GOLDEN);
            x1  = ref_splitmix64(g_s + s_idx * GOLDEN);
            x0  = x1 + a0;
            acc = x0;
            viol = 1'b0;
            halted = 1'b0;
            for (pc = 0; pc < 16; pc = pc + 1) begin
                op = rpn[pc*4 +: 4];
                if (!halted && op == 4'h0) halted = 1'b1;
                else if (!halted) begin
                    case (op)
                        4'h1: acc = acc + x1 + a0;
                        4'h2: acc = (acc >= x1) ? (acc - x1) : 64'd0;
                        4'h3: acc = acc * (x1 | 64'd1);
                        4'h7: if (x1 >= a1 && x0 >= a1) viol = 1'b1;
                        4'h8: begin
                            sum_lo = x0 + x1;
                            carry  = (sum_lo < x0) ? 64'd1 : 64'd0;
                            acc    = sum_lo ^ carry;
                        end
                        4'hF: begin
                            rot = {acc[62:0], acc[63]};
                            acc = acc ^ rot ^ ROTXOR;
                        end
                        default: ;
                    endcase
                end
            end
            ref_verify_sample = viol;
        end
    endfunction

    task automatic run_case(
        input integer case_id,
        input [63:0] b_seed,
        input [63:0] g_idx,
        input [31:0] n_s,
        input [63:0] rpn,
        input [63:0] a0,
        input [63:0] a1
    );
        reg        exp_cex;
        reg [63:0] exp_idx;
        integer    s;
        integer    cycles;
        begin
            exp_cex = 1'b0;
            exp_idx = 64'hFFFFFFFFFFFFFFFF;
            for (s = 0; s < n_s; s = s + 1) begin
                if (!exp_cex && ref_verify_sample(b_seed, g_idx, s, rpn, a0, a1)) begin
                    exp_cex = 1'b1;
                    exp_idx = s;
                end
            end

            @(posedge clk);
            base_seed  <= b_seed;
            goal_idx   <= g_idx;
            n_samples  <= n_s;
            rpn_packed <= rpn;
            arg0       <= a0;
            arg1       <= a1;
            start      <= 1'b1;
            @(posedge clk);
            start      <= 1'b0;

            cycles = 0;
            while (!done_pulse && cycles < 10000) begin
                @(posedge clk);
                cycles = cycles + 1;
            end

            if (!done_pulse) begin
                $display("FAIL case %0d: timeout", case_id);
                $fatal(1);
            end
            if (cex_found !== exp_cex || min_sample_idx !== exp_idx) begin
                $display("FAIL case %0d: got cex=%0d idx=%h, expected cex=%0d idx=%h",
                         case_id, cex_found, min_sample_idx, exp_cex, exp_idx);
                $fatal(1);
            end
            $display("PASS case %0d: cex=%0d min_sample_idx=%h cycles=%0d",
                     case_id, cex_found, min_sample_idx, cycles);
        end
    endtask

    initial begin
        rst_n = 1'b0;
        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        // Case 0: Immediate counterexample at sample 0 (op=7, arg1=1)
        run_case(0, 64'h123456789ABCDEF0, 64'd0, 32'd16, 64'h0000000000000731, 64'd5, 64'd1);
        // Case 1: High threshold arg1=0xFFFFFFFFFFFFFFFF -> no counterexample
        run_case(1, 64'h123456789ABCDEF0, 64'd1, 32'd32, 64'h0000000000000782, 64'd10, 64'hFFFFFFFFFFFFFFFF);
        // Case 2: Mid-stream counterexample (threshold 0xD000000000000000)
        run_case(2, 64'hCAFEBABE00000001, 64'd3, 32'd64, 64'h000000000007F831, 64'd0, 64'hD000000000000000);
        // Case 3: Zero samples edge case
        run_case(3, 64'hCAFEBABE00000001, 64'd4, 32'd0,  64'h0000000000000007, 64'd0, 64'd0);
        // Case 4: Full 16-opcode program without op=7 -> no counterexample
        run_case(4, 64'h0F0E0D0C0B0A0908, 64'd7, 32'd24, 64'hF8321F8321F83211, 64'd42, 64'd100);

        $display("ALL LSC2_FASTCHECK_U256_CORE TESTS PASSED");
        $finish;
    end
endmodule
`default_nettype wire

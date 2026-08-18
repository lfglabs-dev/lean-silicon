`default_nettype none

// Independent behavioural reference for the eight-cell BLAKE3 alias precheck.
// Written as explicit nested loops rather than a generate cross-product so that
// a structural mutation of the DUT cannot be mirrored by the reference.
module lsc1_blake3_alias_check_golden (
    input wire [31:0] message_offset_0, message_offset_1,
    input wire [31:0] message_offset_2, message_offset_3,
    input wire [31:0] cv_offset, out_offset,
    input wire [7:0] cell_present_0, cell_present_1, cell_present_2, cell_present_3,
    input wire [7:0] cell_present_4, cell_present_5, cell_present_6, cell_present_7,
    input wire [127:0] cell_value_0, cell_value_1, cell_value_2, cell_value_3,
    input wire [127:0] cell_value_4, cell_value_5, cell_value_6, cell_value_7,
    output reg alias_inconsistent
);
    integer gi, gj;
    wire [255:0] address = {out_offset + 32'd1, out_offset,
                            cv_offset + 32'd1, cv_offset,
                            message_offset_3, message_offset_2,
                            message_offset_1, message_offset_0};
    wire [63:0] present = {cell_present_7, cell_present_6, cell_present_5, cell_present_4,
                           cell_present_3, cell_present_2, cell_present_1, cell_present_0};
    wire [1023:0] value = {cell_value_7, cell_value_6, cell_value_5, cell_value_4,
                           cell_value_3, cell_value_2, cell_value_1, cell_value_0};
    always @(*) begin
        alias_inconsistent = 1'b0;
        for (gi = 0; gi < 8; gi = gi + 1)
            for (gj = 0; gj < 8; gj = gj + 1)
                if (gj > gi &&
                    address[gi*32 +: 32] == address[gj*32 +: 32] &&
                    (present[gi*8 +: 8] != present[gj*8 +: 8] ||
                     value[gi*128 +: 128] != value[gj*128 +: 128]))
                    alias_inconsistent = 1'b1;
    end
endmodule

module tb_lsc1_blake3_alias_check;
    reg [31:0] off [0:5];
    reg [7:0] pres [0:7];
    reg [127:0] val [0:7];
    wire dut_out, golden_out;
    integer i, trial, seed;
    integer directed_hits, random_hits;

    lsc1_blake3_alias_check dut (
        .message_offset_0(off[0]), .message_offset_1(off[1]),
        .message_offset_2(off[2]), .message_offset_3(off[3]),
        .cv_offset(off[4]), .out_offset(off[5]),
        .cell_present_0(pres[0]), .cell_present_1(pres[1]),
        .cell_present_2(pres[2]), .cell_present_3(pres[3]),
        .cell_present_4(pres[4]), .cell_present_5(pres[5]),
        .cell_present_6(pres[6]), .cell_present_7(pres[7]),
        .cell_value_0(val[0]), .cell_value_1(val[1]),
        .cell_value_2(val[2]), .cell_value_3(val[3]),
        .cell_value_4(val[4]), .cell_value_5(val[5]),
        .cell_value_6(val[6]), .cell_value_7(val[7]),
        .alias_inconsistent(dut_out)
    );

    lsc1_blake3_alias_check_golden golden (
        .message_offset_0(off[0]), .message_offset_1(off[1]),
        .message_offset_2(off[2]), .message_offset_3(off[3]),
        .cv_offset(off[4]), .out_offset(off[5]),
        .cell_present_0(pres[0]), .cell_present_1(pres[1]),
        .cell_present_2(pres[2]), .cell_present_3(pres[3]),
        .cell_present_4(pres[4]), .cell_present_5(pres[5]),
        .cell_present_6(pres[6]), .cell_present_7(pres[7]),
        .cell_value_0(val[0]), .cell_value_1(val[1]),
        .cell_value_2(val[2]), .cell_value_3(val[3]),
        .cell_value_4(val[4]), .cell_value_5(val[5]),
        .cell_value_6(val[6]), .cell_value_7(val[7]),
        .alias_inconsistent(golden_out)
    );

    // Widely separated offsets: the eight derived addresses are pairwise distinct,
    // every cell carries a distinct value, so the predicate must be false.
    task clean_state;
        integer k;
        begin
            off[0] = 32'd100; off[1] = 32'd200; off[2] = 32'd300;
            off[3] = 32'd400; off[4] = 32'd500; off[5] = 32'd600;
            for (k = 0; k < 8; k = k + 1) begin
                pres[k] = 8'd1;
                val[k] = k + 1;
            end
        end
    endtask

    task check(input [255:0] name, input expected);
        begin
            #1;
            if (golden_out !== expected)
                $fatal(1, "%0s: reference disagrees with the stated expectation got=%b expected=%b",
                       name, golden_out, expected);
            if (dut_out !== expected)
                $fatal(1, "%0s: alias_inconsistent got=%b expected=%b",
                       name, dut_out, expected);
            directed_hits = directed_hits + 1;
        end
    endtask

    initial begin
        directed_hits = 0;
        random_hits = 0;

        // No aliasing at all.
        clean_state; check("clean", 1'b0);

        // Two message cells share an address and disagree on value.  This pair is
        // adjacent (0,1), so a predicate that skips adjacent pairs must miss it.
        clean_state; off[1] = off[0]; val[1] = val[0] + 1;
        check("adjacent_value_disagreement", 1'b1);

        // Same address, same presence, different value: the value term alone decides.
        clean_state; off[1] = off[0]; pres[1] = pres[0]; val[1] = 128'd7; val[0] = 128'd9;
        check("value_term_required", 1'b1);

        // Same address, same value, different presence: the presence term alone decides.
        clean_state; off[1] = off[0]; val[1] = val[0]; pres[0] = 8'd1; pres[1] = 8'd2;
        check("present_term_required", 1'b1);

        // Aliasing cells that agree completely are consistent, not a violation.
        clean_state; off[1] = off[0]; pres[1] = pres[0]; val[1] = val[0];
        check("agreeing_alias_is_consistent", 1'b0);

        // A non-adjacent pair (0,3) must also be compared.
        clean_state; off[3] = off[0]; val[3] = val[0] + 1;
        check("distant_pair_compared", 1'b1);

        // The cv companion address must be cv_offset+1: cells 4 and 5 disagree but
        // sit at distinct addresses, so collapsing the pair would invent a violation.
        clean_state; pres[5] = 8'd0; val[5] = 128'd0;
        check("cv_companion_offset", 1'b0);

        // Same obligation for the out companion pair (6,7).
        clean_state; pres[7] = 8'd0; val[7] = 128'd0;
        check("out_companion_offset", 1'b0);

        // cv and out groups must not be interchanged.  With out_offset = cv_offset+1
        // the true collision is (5,6); swapping the two group bases hides it.
        clean_state; off[4] = 32'd500; off[5] = 32'd501;
        pres[4] = 8'd1; val[4] = 128'd77;
        pres[5] = 8'd1; val[5] = 128'd77;
        pres[6] = 8'd2; val[6] = 128'd77;
        check("cv_out_groups_not_swapped", 1'b1);

        // The companion addresses participate in comparisons like any other cell.
        clean_state; off[0] = off[4] + 32'd1; val[0] = val[5] + 1;
        check("companion_participates", 1'b1);

        // Wrap-around: cv_offset = 2^32-1 makes the companion address 0.
        clean_state; off[4] = 32'hffffffff; off[0] = 32'd0; val[0] = val[5] + 1;
        check("companion_wraps_to_zero", 1'b1);

        // A base addend common to all cells cancels: shifting every offset by the
        // same constant must not change the verdict.
        clean_state; off[1] = off[0]; val[1] = val[0] + 1;
        for (i = 0; i < 6; i = i + 1) off[i] = off[i] + 32'hdeadbeef;
        check("common_shift_invariant", 1'b1);

        clean_state;
        for (i = 0; i < 6; i = i + 1) off[i] = off[i] + 32'hdeadbeef;
        check("common_shift_invariant_negative", 1'b0);

        // Constrained randomisation: small offset and value domains so that address
        // collisions and value agreements are frequent rather than astronomically rare.
        seed = 32'd20260818;
        for (trial = 0; trial < 4000; trial = trial + 1) begin
            for (i = 0; i < 6; i = i + 1)
                off[i] = $random(seed) & 32'h1f;
            for (i = 0; i < 8; i = i + 1) begin
                pres[i] = $random(seed) & 8'h3;
                val[i] = $random(seed) & 128'h3;
            end
            #1;
            if (dut_out !== golden_out)
                $fatal(1, "random trial %0d: alias_inconsistent got=%b expected=%b",
                       trial, dut_out, golden_out);
            if (golden_out) random_hits = random_hits + 1;
        end

        if (directed_hits != 13)
            $fatal(1, "expected 13 directed vectors, ran %0d", directed_hits);
        // Guards against a degenerate random domain in which the predicate is never
        // true and the random lane would therefore prove nothing.
        if (random_hits < 100)
            $fatal(1, "random lane produced only %0d positive verdicts", random_hits);

        $display("PASS: %0d directed alias vectors and 4000 constrained random trials (%0d positive)",
                 directed_hits, random_hits);
        $finish;
    end
endmodule

`default_nettype wire

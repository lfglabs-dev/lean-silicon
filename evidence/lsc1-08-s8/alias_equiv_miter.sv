// AC-1 equivalence obligation for the LSC1-08 S8 alias-precheck extraction.
//
// `alias_precheck_base` is a verbatim transcription of the predicate as it stood
// at base commit 392b7d5ef4b750cbf720ddafa960b5b314a74df3, lines 127-170 of
// asic_core/rtl/lsc1_packet_frontend.sv.  The shared addend that the original
// code read from frame_payload[32 +: 32] is lifted here to the free input `base`,
// so the proof quantifies over every one of its 2^32 values rather than a sample.
//
// `alias_precheck_head` instantiates the shipped module itself, not a copy of it,
// so the proof binds the artifact that is actually compiled into the design.
//
// Reproduce with:
//   yosys -p 'read_verilog -sv asic_core/rtl/lsc1_blake3_alias_check.sv \
//             evidence/lsc1-08-s8/alias_equiv_miter.sv; prep; \
//             miter -equiv -flatten -make_assert alias_precheck_base \
//             alias_precheck_head miter; hierarchy -top miter; \
//             sat -verify -prove-asserts -set-def-inputs'
//
// Expected: "SAT proof finished - no model found: SUCCESS!" and exit status 0.
//
// The companion non-vacuity obligation replaces `o4 + 1'b1` with `o4 + 2'd2` in
// the head instance's companion address and must instead report
// "Called with -verify and proof did fail!" with exit status 1.  Without that
// second run a miter that proved nothing would be indistinguishable from a
// miter that proved equivalence.

`default_nettype none

module alias_precheck_base (
    input wire [31:0] o0, o1, o2, o3, o4, o6, base,
    input wire [7:0] p0, p1, p2, p3, p4, p5, p6, p7,
    input wire [127:0] v0, v1, v2, v3, v4, v5, v6, v7,
    output wire alias_inconsistent
);
    wire [31:0] blake_address [0:7];
    wire [7:0] blake_present [0:7];
    wire [127:0] blake_value [0:7];
    wire [63:0] blake_alias_pair;

    assign blake_address[0] = o0 + base;
    assign blake_address[1] = o1 + base;
    assign blake_address[2] = o2 + base;
    assign blake_address[3] = o3 + base;
    assign blake_address[4] = o4 + base;
    assign blake_address[5] = blake_address[4] + 1'b1;
    assign blake_address[6] = o6 + base;
    assign blake_address[7] = blake_address[6] + 1'b1;
    assign blake_present[0] = p0;
    assign blake_present[1] = p1;
    assign blake_present[2] = p2;
    assign blake_present[3] = p3;
    assign blake_present[4] = p4;
    assign blake_present[5] = p5;
    assign blake_present[6] = p6;
    assign blake_present[7] = p7;
    assign blake_value[0] = v0;
    assign blake_value[1] = v1;
    assign blake_value[2] = v2;
    assign blake_value[3] = v3;
    assign blake_value[4] = v4;
    assign blake_value[5] = v5;
    assign blake_value[6] = v6;
    assign blake_value[7] = v7;

    genvar alias_i, alias_j;
    generate
        for (alias_i = 0; alias_i < 8; alias_i = alias_i + 1) begin : g_alias_i
            for (alias_j = 0; alias_j < 8; alias_j = alias_j + 1) begin : g_alias_j
                if (alias_j > alias_i)
                    assign blake_alias_pair[alias_i*8+alias_j] =
                        blake_address[alias_i] == blake_address[alias_j] &&
                        (blake_present[alias_i] != blake_present[alias_j] ||
                         blake_value[alias_i] != blake_value[alias_j]);
                else
                    assign blake_alias_pair[alias_i*8+alias_j] = 1'b0;
            end
        end
    endgenerate

    assign alias_inconsistent = |blake_alias_pair;
endmodule

// `base` is declared but deliberately unread: that the head predicate ignores it
// is the dead-addend claim, and the miter is what discharges it.
module alias_precheck_head (
    input wire [31:0] o0, o1, o2, o3, o4, o6, base,
    input wire [7:0] p0, p1, p2, p3, p4, p5, p6, p7,
    input wire [127:0] v0, v1, v2, v3, v4, v5, v6, v7,
    output wire alias_inconsistent
);
    lsc1_blake3_alias_check shipped (
        .message_offset_0(o0),
        .message_offset_1(o1),
        .message_offset_2(o2),
        .message_offset_3(o3),
        .cv_offset(o4),
        .out_offset(o6),
        .cell_present_0(p0), .cell_present_1(p1),
        .cell_present_2(p2), .cell_present_3(p3),
        .cell_present_4(p4), .cell_present_5(p5),
        .cell_present_6(p6), .cell_present_7(p7),
        .cell_value_0(v0), .cell_value_1(v1),
        .cell_value_2(v2), .cell_value_3(v3),
        .cell_value_4(v4), .cell_value_5(v5),
        .cell_value_6(v6), .cell_value_7(v7),
        .alias_inconsistent(alias_inconsistent)
    );
endmodule

`default_nettype wire

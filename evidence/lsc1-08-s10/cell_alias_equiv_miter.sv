// AC-1 equivalence obligation for the LSC1-08 S10 cell-alias-precheck extraction.
//
// `cell_alias_base` is a verbatim transcription of the predicate as it stood at
// base commit 497b905bbd85b85eaa3d222ab9775fdb1b27b643: the DEREF arm at lines
// 876-886, the JUMP arm at lines 910-922 and the XOR/MUL arm at lines 964-976 of
// asic_core/rtl/lsc1_packet_frontend.sv.  Every quantity is read here from the
// same raw bit offset of frame_payload that the base arms read it from, and the
// arm dispatch reproduces the base decode ladder's opcode tests, so the base side
// of the miter is a frozen copy of the deleted code rather than a restatement of
// it in the extracted module's vocabulary.
//
// Opcodes outside the three arms are tied low on both sides.  The base frontend
// never evaluated the predicate for them, so its value there was a don't-care;
// tying it low makes both sides total functions and turns the obligation into a
// comparison of two total functions with no don't-care reasoning.  What preserves
// the fault priority is the ladder position of the three uses, which this slice
// does not move, and which the AC-5 directed frontend differential pins.
//
// `cell_alias_head` instantiates the shipped module itself, not a copy of it, so
// the proof binds the artifact that is actually compiled into the design.  The
// quantification is over the whole 656-bit input space (frame_opcode[7:0] and
// frame_payload[647:0]); nothing is sampled and nothing is constrained.
//
// Reproduce with:
//   yosys -p 'read_verilog -sv asic_core/rtl/lsc1_cell_alias_check.sv \
//             evidence/lsc1-08-s10/cell_alias_equiv_miter.sv; prep; \
//             miter -equiv -flatten -make_assert cell_alias_base \
//             cell_alias_head miter; hierarchy -top miter; \
//             sat -verify -prove-asserts -set-def-inputs'
//
// Expected: "SAT proof finished - no model found: SUCCESS!" and exit status 0.
//
// The companion non-vacuity obligations perturb a *copy* of the shipped module
// and must each instead report "Called with -verify and proof did fail!" with
// exit status 1.  Without them a miter that proved nothing would be
// indistinguishable from a miter that proved equivalence.  The four perturbations
// are: drop the a-c pair; give the DEREF middle address fp instead of base_index;
// move the DEREF cell-b offset from 47 to 43; and give the non-DEREF arms the
// DEREF cell offsets.  They are driven by check_cell_alias_equiv.sh.

`default_nettype none

module cell_alias_base (
    input  wire [7:0]   frame_opcode,
    input  wire [647:0] frame_payload,
    output reg          alias_inconsistent
);
    reg [31:0] fp, off_a, off_b, off_c, base_index;
    reg [31:0] addr_a, addr_b, addr_c;
    reg [7:0] pres_a, pres_b, pres_c;
    reg [127:0] val_a, val_b, val_c;

    always @(*) begin
        fp = frame_payload[64 +: 32];
        off_a = frame_payload[112 +: 32];
        off_b = frame_payload[144 +: 32];
        off_c = frame_payload[176 +: 32];
        base_index = frame_payload[43*8 +: 32];
        pres_a = frame_payload[26*8 +: 8];
        val_a = frame_payload[216 +: 128];
        alias_inconsistent = 1'b0;

        if (frame_opcode == 8'h04 || frame_opcode == 8'h05 || frame_opcode == 8'h06) begin
            // DEREF_CELL / DEREF_PC / DEREF_FP
            pres_b = frame_payload[47*8 +: 8];
            val_b = frame_payload[384 +: 128];
            pres_c = frame_payload[64*8 +: 8];
            val_c = frame_payload[520 +: 128];
            addr_a = fp + off_a;
            addr_b = base_index + off_b;
            addr_c = fp + off_c;
            alias_inconsistent =
                (addr_a == addr_b && (pres_a != pres_b || val_a != val_b)) ||
                (addr_a == addr_c && (pres_a != pres_c || val_a != val_c)) ||
                (addr_b == addr_c && (pres_b != pres_c || val_b != val_c));
        end else if (frame_opcode == 8'h07 || frame_opcode == 8'h01 ||
                     frame_opcode == 8'h02) begin
            // JUMP / XOR / MUL
            pres_b = frame_payload[43*8 +: 8];
            val_b = frame_payload[352 +: 128];
            pres_c = frame_payload[60*8 +: 8];
            val_c = frame_payload[488 +: 128];
            addr_a = fp + off_a;
            addr_b = fp + off_b;
            addr_c = fp + off_c;
            alias_inconsistent =
                (addr_a == addr_b && (pres_a != pres_b || val_a != val_b)) ||
                (addr_a == addr_c && (pres_a != pres_c || val_a != val_c)) ||
                (addr_b == addr_c && (pres_b != pres_c || val_b != val_c));
        end else begin
            pres_b = 8'd0; val_b = 128'd0;
            pres_c = 8'd0; val_c = 128'd0;
            addr_a = 32'd0; addr_b = 32'd0; addr_c = 32'd0;
        end
    end
endmodule

module cell_alias_head (
    input  wire [7:0]   frame_opcode,
    input  wire [647:0] frame_payload,
    output wire         alias_inconsistent
);
    lsc1_cell_alias_check shipped (
        .frame_opcode(frame_opcode),
        .frame_payload(frame_payload),
        .alias_inconsistent(alias_inconsistent)
    );
endmodule

`default_nettype wire

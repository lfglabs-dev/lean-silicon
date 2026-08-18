`default_nettype none

// Purely combinational alias precheck for the three scalar cells carried by a
// compute request frame: reports whether any two of them name the same address
// while disagreeing on presence or value.  Three byte-identical inline copies of
// this predicate previously sat in the DEREF, JUMP and XOR/MUL arms of the packet
// frontend's decode ladder.
//
// The predicate is stated here as a total function of the frame.  The frontend
// evaluates it only inside three arms, and only after the cell-malformedness and
// overflow tests ahead of it have passed; the value for every other opcode was
// therefore a don't-care.  Tying those opcodes low makes the extracted function
// total, so the equivalence obligation is a comparison of two total functions
// with no don't-care reasoning.  The ladder position of each of the three uses is
// unchanged, which is what preserves the fault priority.
//
// The port list takes the frame rather than the frontend's decoded scratch regs
// (`addr_a`, `pres_a`, `val_a`, ...) on purpose.  Those are procedural regs
// written with blocking assignments inside a clocked block, while this module's
// outputs settle through continuous assignments in a different delta cycle, so a
// frontend that drove this instance from them would read back the previous
// frame's verdict -- correct under synthesis, silently stale in simulation.  This
// is the same hazard `lsc1_request_validator` documents for its function
// arguments.
module lsc1_cell_alias_check (
    input  wire [7:0]   frame_opcode,
    input  wire [647:0] frame_payload,
    output wire         alias_inconsistent
);
    localparam [7:0] OP_XOR = 8'h01, OP_MUL = 8'h02,
                     OP_DEREF_CELL = 8'h04, OP_DEREF_PC = 8'h05,
                     OP_DEREF_FP = 8'h06, OP_JUMP = 8'h07;

    // Byte offsets into frame_payload.  A cell occupies 17 bytes: a presence byte
    // at the offset named here, then its 128-bit value at the following byte.
    // The DEREF and scalar frame layouts agree on cell 0 and diverge on cells 1
    // and 2; DEREF alone addresses cell 1 from `base_index` instead of `fp`.
    localparam integer FP_AT = 8;
    localparam integer OFFSET_A_AT = 14;
    localparam integer OFFSET_B_AT = 18;
    localparam integer OFFSET_C_AT = 22;
    localparam integer BASE_INDEX_AT = 43;
    localparam integer CELL_0_AT = 26;
    localparam integer DEREF_CELL_1_AT = 47;
    localparam integer DEREF_CELL_2_AT = 64;
    localparam integer SCALAR_CELL_1_AT = 43;
    localparam integer SCALAR_CELL_2_AT = 60;

    wire is_deref = frame_opcode == OP_DEREF_CELL ||
                    frame_opcode == OP_DEREF_PC ||
                    frame_opcode == OP_DEREF_FP;
    wire is_scalar = frame_opcode == OP_JUMP ||
                     frame_opcode == OP_XOR ||
                     frame_opcode == OP_MUL;
    wire checked = is_deref || is_scalar;

    wire [31:0] fp = frame_payload[FP_AT*8 +: 32];
    wire [31:0] offset_a = frame_payload[OFFSET_A_AT*8 +: 32];
    wire [31:0] offset_b = frame_payload[OFFSET_B_AT*8 +: 32];
    wire [31:0] offset_c = frame_payload[OFFSET_C_AT*8 +: 32];
    wire [31:0] base_index = frame_payload[BASE_INDEX_AT*8 +: 32];

    wire [31:0] address_a = fp + offset_a;
    wire [31:0] address_b = is_deref ? base_index + offset_b : fp + offset_b;
    wire [31:0] address_c = fp + offset_c;

    wire [7:0] present_a = frame_payload[CELL_0_AT*8 +: 8];
    wire [127:0] value_a = frame_payload[(CELL_0_AT + 1)*8 +: 128];
    wire [7:0] present_b = is_deref ? frame_payload[DEREF_CELL_1_AT*8 +: 8]
                                    : frame_payload[SCALAR_CELL_1_AT*8 +: 8];
    wire [127:0] value_b = is_deref ? frame_payload[(DEREF_CELL_1_AT + 1)*8 +: 128]
                                    : frame_payload[(SCALAR_CELL_1_AT + 1)*8 +: 128];
    wire [7:0] present_c = is_deref ? frame_payload[DEREF_CELL_2_AT*8 +: 8]
                                    : frame_payload[SCALAR_CELL_2_AT*8 +: 8];
    wire [127:0] value_c = is_deref ? frame_payload[(DEREF_CELL_2_AT + 1)*8 +: 128]
                                    : frame_payload[(SCALAR_CELL_2_AT + 1)*8 +: 128];

    // Arguments are passed in explicitly rather than indexed out of
    // `frame_payload` inside the function, for the reason given in the header of
    // `lsc1_request_validator`: a continuous assignment takes its sensitivity from
    // the arguments of the call.
    function automatic pair_inconsistent;
        input [31:0] address_x, address_y;
        input [7:0] present_x, present_y;
        input [127:0] value_x, value_y;
        begin
            pair_inconsistent = address_x == address_y &&
                                (present_x != present_y || value_x != value_y);
        end
    endfunction

    wire alias_ab = pair_inconsistent(address_a, address_b, present_a, present_b,
                                      value_a, value_b);
    wire alias_ac = pair_inconsistent(address_a, address_c, present_a, present_c,
                                      value_a, value_c);
    wire alias_bc = pair_inconsistent(address_b, address_c, present_b, present_c,
                                      value_b, value_c);

    assign alias_inconsistent = checked && (alias_ab || alias_ac || alias_bc);

endmodule

`default_nettype wire

`default_nettype none

// Purely combinational admission check for compute request frames.  It reports
// whether the static contents of a frame reject it before dispatch, and with
// which fault triple, so the packet frontend can reduce eleven inline `else if`
// arms to one.
//
// The priority order below is the specified behaviour, not an implementation
// detail: a frame that matches several predicates reports the fault of the
// highest arm.  Two orderings in particular are load-bearing and must not be
// tidied.  The cell scan outranks the JUMP branch-proposal check, which is what
// the wire protocol has always done and what LSC1-08 R10 tracks against the
// executable model.  The pending-state check is last, so a malformed frame is
// rejected on its contents even while a result is outstanding.
module lsc1_request_validator (
    input  wire [7:0]    frame_opcode,
    input  wire [15:0]   frame_length,
    input  wire [1519:0] frame_payload,
    input  wire          result_pending,
    input  wire          blake_result_pending,
    input  wire          blake_service_pending,
    output reg           reject,
    output reg  [7:0]    fault_status,
    output reg  [31:0]   fault_txn,
    output reg  [7:0]    fault_detail
);
    localparam [7:0] OP_XOR = 8'h01, OP_MUL = 8'h02, OP_SET = 8'h03,
                     OP_DEREF_CELL = 8'h04, OP_DEREF_PC = 8'h05,
                     OP_DEREF_FP = 8'h06, OP_JUMP = 8'h07,
                     OP_BLAKE3 = 8'h08;
    localparam [7:0] BAD_OPCODE = 8'h82, BAD_LENGTH = 8'h83,
                     BAD_FLAGS = 8'h85, BAD_PROFILE = 8'h86,
                     BAD_STATE = 8'h87, BAD_CELL = 8'h88,
                     BAD_BRANCH_PROPOSAL = 8'h8f;

    // Byte offsets into frame_payload.  A cell occupies 17 bytes: a presence byte
    // at the offset named here, then its 128-bit value at the following byte.
    localparam integer TXN_AT = 0;
    localparam integer PROFILE_AT = 12;
    localparam integer FLAGS_AT = 13;
    localparam integer SET_CELL_AT = 34;
    localparam integer DEREF_CELL_0_AT = 26;
    localparam integer DEREF_CELL_1_AT = 47;
    localparam integer DEREF_CELL_2_AT = 64;
    localparam integer JUMP_CELL_0_AT = 26;
    localparam integer JUMP_CELL_1_AT = 43;
    localparam integer JUMP_CELL_2_AT = 60;
    localparam integer JUMP_CELL_3_AT = 86;
    localparam integer JUMP_PROPOSAL_AT = 77;
    localparam integer BLAKE_CELL_BASE_AT = 54;
    localparam integer BLAKE_CELL_STRIDE = 17;
    localparam integer ALU_CELL_0_AT = 26;
    localparam integer ALU_CELL_1_AT = 43;
    localparam integer ALU_CELL_2_AT = 60;
    localparam integer MUL_CELL_3_AT = 77;

    wire is_xor = frame_opcode == OP_XOR;
    wire is_mul = frame_opcode == OP_MUL;
    wire is_set = frame_opcode == OP_SET;
    wire is_jump = frame_opcode == OP_JUMP;
    wire is_blake3 = frame_opcode == OP_BLAKE3;
    wire is_deref = frame_opcode == OP_DEREF_CELL ||
                    frame_opcode == OP_DEREF_PC ||
                    frame_opcode == OP_DEREF_FP;
    wire is_alu = is_xor || is_mul;
    wire is_compute = is_alu || is_set || is_deref || is_jump || is_blake3;

    // One length table replaces a six-disjunct comparison.  Unknown opcodes take
    // the default and so never disagree; they are rejected by `bad_opcode`, which
    // outranks `bad_length` in the chain below.
    reg [15:0] expected_length;
    always @(*) begin
        case (frame_opcode)
            OP_SET:        expected_length = 16'd51;
            OP_XOR:        expected_length = 16'd77;
            OP_MUL:        expected_length = 16'd94;
            OP_DEREF_CELL,
            OP_DEREF_PC,
            OP_DEREF_FP:   expected_length = 16'd81;
            OP_JUMP:       expected_length = 16'd103;
            OP_BLAKE3:     expected_length = 16'd190;
            default:       expected_length = frame_length;
        endcase
    end

    // The presence byte and the value are passed in explicitly rather than read
    // from `frame_payload` inside the function.  A continuous assignment takes its
    // sensitivity from the arguments of the call, so a function that reached for
    // `frame_payload` itself would be evaluated once and then never again when the
    // offsets are constants -- correct under synthesis, silently stale in
    // simulation.  The offset localparams below are the only place an offset is
    // written down.
    function automatic cell_malformed;
        input [7:0] cell_present;
        input [127:0] cell_value;
        begin
            cell_malformed = cell_present > 1 || (!cell_present && cell_value != 0);
        end
    endfunction

    wire [7:0] blake_cell_bad;
    genvar blake_i;
    generate
        for (blake_i = 0; blake_i < 8; blake_i = blake_i + 1) begin : g_blake_cell
            localparam integer AT = BLAKE_CELL_BASE_AT + blake_i*BLAKE_CELL_STRIDE;
            assign blake_cell_bad[blake_i] =
                cell_malformed(frame_payload[AT*8 +: 8],
                               frame_payload[(AT + 1)*8 +: 128]);
        end
    endgenerate

    wire set_cells_bad =
        cell_malformed(frame_payload[SET_CELL_AT*8 +: 8],
                       frame_payload[(SET_CELL_AT + 1)*8 +: 128]);
    wire deref_cells_bad =
        cell_malformed(frame_payload[DEREF_CELL_0_AT*8 +: 8],
                       frame_payload[(DEREF_CELL_0_AT + 1)*8 +: 128]) ||
        cell_malformed(frame_payload[DEREF_CELL_1_AT*8 +: 8],
                       frame_payload[(DEREF_CELL_1_AT + 1)*8 +: 128]) ||
        cell_malformed(frame_payload[DEREF_CELL_2_AT*8 +: 8],
                       frame_payload[(DEREF_CELL_2_AT + 1)*8 +: 128]);
    wire jump_cells_bad =
        cell_malformed(frame_payload[JUMP_CELL_0_AT*8 +: 8],
                       frame_payload[(JUMP_CELL_0_AT + 1)*8 +: 128]) ||
        cell_malformed(frame_payload[JUMP_CELL_1_AT*8 +: 8],
                       frame_payload[(JUMP_CELL_1_AT + 1)*8 +: 128]) ||
        cell_malformed(frame_payload[JUMP_CELL_2_AT*8 +: 8],
                       frame_payload[(JUMP_CELL_2_AT + 1)*8 +: 128]) ||
        cell_malformed(frame_payload[JUMP_CELL_3_AT*8 +: 8],
                       frame_payload[(JUMP_CELL_3_AT + 1)*8 +: 128]);
    wire alu_cells_bad =
        cell_malformed(frame_payload[ALU_CELL_0_AT*8 +: 8],
                       frame_payload[(ALU_CELL_0_AT + 1)*8 +: 128]) ||
        cell_malformed(frame_payload[ALU_CELL_1_AT*8 +: 8],
                       frame_payload[(ALU_CELL_1_AT + 1)*8 +: 128]) ||
        cell_malformed(frame_payload[ALU_CELL_2_AT*8 +: 8],
                       frame_payload[(ALU_CELL_2_AT + 1)*8 +: 128]) ||
        (is_mul && cell_malformed(frame_payload[MUL_CELL_3_AT*8 +: 8],
                                  frame_payload[(MUL_CELL_3_AT + 1)*8 +: 128]));

    wire [31:0] payload_txn = frame_payload[TXN_AT*8 +: 32];

    wire bad_opcode = !is_compute;
    wire bad_length = frame_length != expected_length;
    wire bad_profile = frame_payload[PROFILE_AT*8 +: 8] > 1;
    wire bad_flags = frame_payload[FLAGS_AT*8 +: 8] != 0;
    wire cells_bad = (is_set && set_cells_bad) ||
                     (is_deref && deref_cells_bad) ||
                     (is_jump && jump_cells_bad) ||
                     (is_blake3 && |blake_cell_bad) ||
                     (is_alu && alu_cells_bad);
    wire bad_proposal = is_jump && frame_payload[JUMP_PROPOSAL_AT*8 +: 8] > 1;
    wire bad_state = result_pending || blake_result_pending || blake_service_pending;

    task automatic fault;
        input [7:0] status;
        input [31:0] txn;
        input [7:0] detail;
        begin
            reject = 1'b1;
            fault_status = status;
            fault_txn = txn;
            fault_detail = detail;
        end
    endtask

    always @(*) begin
        reject = 1'b0;
        fault_status = 8'd0;
        fault_txn = 32'd0;
        fault_detail = 8'd0;
        if (bad_opcode) begin
            fault(BAD_OPCODE, 32'd0, 8'd0);
        end else if (bad_length) begin
            fault(BAD_LENGTH, payload_txn, 8'd2);
        end else if (bad_profile) begin
            fault(BAD_PROFILE, 32'd0, 8'd0);
        end else if (bad_flags) begin
            fault(BAD_FLAGS, 32'd0, 8'd1);
        end else if (cells_bad) begin
            fault(BAD_CELL, 32'd0, 8'd0);
        end else if (bad_proposal) begin
            fault(BAD_BRANCH_PROPOSAL, 32'd0, 8'd3);
        end else if (bad_state) begin
            fault(BAD_STATE, payload_txn, 8'd0);
        end
    end

endmodule

`default_nettype wire

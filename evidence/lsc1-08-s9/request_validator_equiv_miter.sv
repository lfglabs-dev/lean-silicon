// AC-1 equivalence obligation for the LSC1-08 S9 request-validation extraction.
//
// `request_validation_base` is a verbatim transcription of the static request
// validation chain as it stood at base commit
// d2e9d250b426b11fb6f6155e28ac57d36a85d460, lines 739-814 of
// asic_core/rtl/lsc1_packet_frontend.sv.  The 76 lines below were copied out of
// that file mechanically; the single edit applied is that line 739 begins
// `end else if` because the region starts mid-ladder, and that leading `end else`
// is dropped so the chain stands alone.  Indentation is left as it was so the
// transcription can be diffed against the base file byte for byte.
//
// `emit_fault` and `cell_is_malformed` are copied from the same file (lines
// 299-314 and 316-322).  In the frontend `emit_fault` writes eight registers; the
// only part of it this block decides is the argument triple, so here it records
// that triple and raises `reject`.  Every path assigns all four outputs, and the
// non-rejecting case drives them to zero on both sides, so the miter constrains
// the outputs over the entire input space rather than only where `reject` holds.
//
// `request_validation_head` instantiates the shipped module itself, not a copy of
// it, so the proof binds the artifact that is actually compiled into the design.
//
// Reproduce with:
//   yosys -p 'read_verilog -sv asic_core/rtl/lsc1_request_validator.sv \
//             evidence/lsc1-08-s9/request_validator_equiv_miter.sv; prep; \
//             miter -equiv -flatten -make_assert request_validation_base \
//             request_validation_head miter; hierarchy -top miter; \
//             sat -verify -prove-asserts -set-def-inputs'
//
// Expected: "SAT proof finished - no model found: SUCCESS!" and exit status 0,
// quantified over all 1547 free input bits (8 + 16 + 1520 + 1 + 1 + 1).
//
// The companion non-vacuity obligations perturb the head module -- JUMP length
// 103 -> 102, a cell offset 43 -> 44, BAD_LENGTH detail 2 -> 1, and
// BAD_PROFILE -> BAD_FLAGS -- and must each instead report
// "Called with -verify and proof did fail!" with exit status 1.  Without those
// runs a miter that proved nothing would be indistinguishable from a miter that
// proved equivalence.

`default_nettype none

module request_validation_base (
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

    task automatic emit_fault;
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

    function automatic cell_is_malformed;
        input [7:0] present;
        input [127:0] value;
        begin
            cell_is_malformed = present > 1 || (!present && value != 0);
        end
    endfunction

    always @(*) begin
        reject = 1'b0;
        fault_status = 8'd0;
        fault_txn = 32'd0;
        fault_detail = 8'd0;
                if (frame_opcode != OP_XOR &&
                             frame_opcode != OP_MUL &&
                             frame_opcode != OP_SET &&
                             frame_opcode != OP_DEREF_CELL &&
                             frame_opcode != OP_DEREF_PC &&
                             frame_opcode != OP_DEREF_FP &&
                             frame_opcode != OP_JUMP &&
                             frame_opcode != OP_BLAKE3) begin
                    emit_fault(BAD_OPCODE, 0, 0);
                end else if ((frame_opcode == OP_SET && frame_length != 51) ||
                             (frame_opcode == OP_XOR && frame_length != 77) ||
                             (frame_opcode == OP_MUL && frame_length != 94) ||
                             ((frame_opcode == OP_DEREF_CELL ||
                               frame_opcode == OP_DEREF_PC ||
                               frame_opcode == OP_DEREF_FP) && frame_length != 81) ||
                             (frame_opcode == OP_JUMP && frame_length != 103) ||
                             (frame_opcode == OP_BLAKE3 && frame_length != 190)) begin
                    emit_fault(BAD_LENGTH, frame_payload[0 +: 32], 2);
                // Match decode_request_payload: malformed payloads are rejected
                // before dispatch sees the pending transaction, and decoder
                // faults do not acquire the payload transaction ID.
                end else if (frame_payload[12*8 +: 8] > 1) begin
                    emit_fault(BAD_PROFILE, 0, 0);
                end else if (frame_payload[13*8 +: 8] != 0) begin
                    emit_fault(BAD_FLAGS, 0, 1);
                end else if (frame_opcode == OP_SET &&
                             cell_is_malformed(frame_payload[34*8 +: 8],
                                               frame_payload[280 +: 128])) begin
                    emit_fault(BAD_CELL, 0, 0);
                end else if ((frame_opcode == OP_DEREF_CELL ||
                              frame_opcode == OP_DEREF_PC ||
                              frame_opcode == OP_DEREF_FP) &&
                             (cell_is_malformed(frame_payload[26*8 +: 8],
                                                frame_payload[216 +: 128]) ||
                              cell_is_malformed(frame_payload[47*8 +: 8],
                                                frame_payload[384 +: 128]) ||
                              cell_is_malformed(frame_payload[64*8 +: 8],
                                                frame_payload[520 +: 128]))) begin
                    emit_fault(BAD_CELL, 0, 0);
                end else if (frame_opcode == OP_JUMP &&
                             (cell_is_malformed(frame_payload[26*8 +: 8],
                                                frame_payload[216 +: 128]) ||
                              cell_is_malformed(frame_payload[43*8 +: 8],
                                                frame_payload[352 +: 128]) ||
                              cell_is_malformed(frame_payload[60*8 +: 8],
                                                frame_payload[488 +: 128]) ||
                              cell_is_malformed(frame_payload[86*8 +: 8],
                                                frame_payload[696 +: 128]))) begin
                    emit_fault(BAD_CELL, 0, 0);
                end else if (frame_opcode == OP_JUMP &&
                             frame_payload[77*8 +: 8] > 1) begin
                    emit_fault(BAD_BRANCH_PROPOSAL, 0, 3);
                end else if (frame_opcode == OP_BLAKE3 &&
                             (cell_is_malformed(frame_payload[54*8 +: 8], frame_payload[55*8 +: 128]) ||
                              cell_is_malformed(frame_payload[71*8 +: 8], frame_payload[72*8 +: 128]) ||
                              cell_is_malformed(frame_payload[88*8 +: 8], frame_payload[89*8 +: 128]) ||
                              cell_is_malformed(frame_payload[105*8 +: 8], frame_payload[106*8 +: 128]) ||
                              cell_is_malformed(frame_payload[122*8 +: 8], frame_payload[123*8 +: 128]) ||
                              cell_is_malformed(frame_payload[139*8 +: 8], frame_payload[140*8 +: 128]) ||
                              cell_is_malformed(frame_payload[156*8 +: 8], frame_payload[157*8 +: 128]) ||
                              cell_is_malformed(frame_payload[173*8 +: 8], frame_payload[174*8 +: 128]))) begin
                    emit_fault(BAD_CELL, 0, 0);
                end else if ((frame_opcode == OP_XOR || frame_opcode == OP_MUL) &&
                             (cell_is_malformed(frame_payload[26*8 +: 8],
                                                frame_payload[216 +: 128]) ||
                              cell_is_malformed(frame_payload[43*8 +: 8],
                                                frame_payload[352 +: 128]) ||
                              cell_is_malformed(frame_payload[60*8 +: 8],
                                                frame_payload[488 +: 128]) ||
                              (frame_opcode == OP_MUL &&
                               cell_is_malformed(frame_payload[77*8 +: 8],
                                                 frame_payload[624 +: 128])))) begin
                    emit_fault(BAD_CELL, 0, 0);
                end else if (result_pending ||
                             blake_result_pending || blake_service_pending) begin
                    emit_fault(BAD_STATE, frame_payload[0 +: 32], 0);
                end
    end
endmodule

module request_validation_head (
    input  wire [7:0]    frame_opcode,
    input  wire [15:0]   frame_length,
    input  wire [1519:0] frame_payload,
    input  wire          result_pending,
    input  wire          blake_result_pending,
    input  wire          blake_service_pending,
    output wire          reject,
    output wire [7:0]    fault_status,
    output wire [31:0]   fault_txn,
    output wire [7:0]    fault_detail
);
    lsc1_request_validator shipped (
        .frame_opcode(frame_opcode),
        .frame_length(frame_length),
        .frame_payload(frame_payload),
        .result_pending(result_pending),
        .blake_result_pending(blake_result_pending),
        .blake_service_pending(blake_service_pending),
        .reject(reject),
        .fault_status(fault_status),
        .fault_txn(fault_txn),
        .fault_detail(fault_detail)
    );
endmodule

`default_nettype wire

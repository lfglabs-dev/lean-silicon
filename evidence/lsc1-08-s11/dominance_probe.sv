`default_nettype none

// LSC1-08 S11 AC-1 dominance probe.
//
// Obligation: the five static admission predicates that S11 deletes from the
// lsc1_packet_frontend decode ladder are unreachable, because the ladder sits on
// the `else` branch of `request_reject` (lsc1_packet_frontend.sv:768-771) and the
// shipped lsc1_request_validator already rejects every frame that satisfies any
// of them.
//
// The probe instantiates the SHIPPED, UNMODIFIED validator and pairs it with
// frozen transcriptions of the five predicates exactly as they stand at base
// a28e00656ba886288af24d9f3cd0cafd7796eb7e:
//
//   P1  lsc1_packet_frontend.sv:860-861  SET       -> BAD_CELL
//   P2  lsc1_packet_frontend.sv:892-895  DEREF     -> BAD_CELL
//   P3  lsc1_packet_frontend.sv:927-931  JUMP      -> BAD_CELL
//   P4  lsc1_packet_frontend.sv:936-938  JUMP      -> BAD_BRANCH_PROPOSAL, detail 3
//   P5  lsc1_packet_frontend.sv:979-983  XOR/MUL   -> BAD_CELL
//
// Every quantity is read from the same raw bit offset of frame_payload that the
// base arm reads it from; the offsets are written as literal expressions copied
// from the frontend rather than as localparams, so that a drift between the
// frontend and the validator's offset localparams cannot be hidden by a shared
// definition.
//
// Arm guards are deliberately WEAKER than the RTL's. The frontend enters an arm
// only when `decision_ok` still holds and only after the earlier arms of the
// same if/else-if chain have been excluded; and P4 additionally sits behind the
// U32_OVERFLOW, P3 and cell_alias_inconsistent arms. Dropping those conditions
// enlarges the set of inputs the proof must discharge, so an UNSAT result here
// is strictly stronger than the reachability question actually asked.
module dominance_probe (
    input  wire [7:0]    frame_opcode,
    input  wire [15:0]   frame_length,
    input  wire [1519:0] frame_payload,
    input  wire          result_pending,
    input  wire          blake_result_pending,
    input  wire          blake_service_pending,
    output wire          viol_set,
    output wire          viol_deref,
    output wire          viol_jump_cell,
    output wire          viol_jump_prop,
    output wire          viol_alu,
    output wire          viol_any
);
    localparam [7:0] OP_XOR = 8'h01, OP_MUL = 8'h02, OP_SET = 8'h03,
                     OP_DEREF_CELL = 8'h04, OP_DEREF_PC = 8'h05,
                     OP_DEREF_FP = 8'h06, OP_JUMP = 8'h07,
                     OP_BLAKE3 = 8'h08;

    // ---------------------------------------------------------------------
    // The shipped validator, instantiated verbatim as the frontend does at
    // lsc1_packet_frontend.sv:166-177.
    // ---------------------------------------------------------------------
    wire        request_reject;
    wire [7:0]  request_fault_status, request_fault_detail;
    wire [31:0] request_fault_txn;

    lsc1_request_validator request_validator (
        .frame_opcode(frame_opcode),
        .frame_length(frame_length),
        .frame_payload(frame_payload[1519:0]),
        .result_pending(result_pending),
        .blake_result_pending(blake_result_pending),
        .blake_service_pending(blake_service_pending),
        .reject(request_reject),
        .fault_status(request_fault_status),
        .fault_txn(request_fault_txn),
        .fault_detail(request_fault_detail)
    );

    // ---------------------------------------------------------------------
    // Arm dispatch, transcribed from the decode ladder's if/else-if chain:
    //   :800 BLAKE3   :853 SET   :872 DEREF   :909 JUMP   :964 catch-all
    // The catch-all carries no opcode test in the RTL, so it is transcribed
    // here as the negation of the four preceding opcode tests.
    // ---------------------------------------------------------------------
    wire arm_set   = frame_opcode == OP_SET;
    wire arm_deref = frame_opcode == OP_DEREF_CELL ||
                     frame_opcode == OP_DEREF_PC ||
                     frame_opcode == OP_DEREF_FP;
    wire arm_jump  = frame_opcode == OP_JUMP;
    wire arm_alu   = !(frame_opcode == OP_BLAKE3) && !arm_set &&
                     !arm_deref && !arm_jump;

    // ---------------------------------------------------------------------
    // P1 -- SET arm, lsc1_packet_frontend.sv:856-857 (reads) / :860 (predicate)
    // ---------------------------------------------------------------------
    wire [7:0]   set_pres_a = frame_payload[34*8 +: 8];
    wire [127:0] set_val_a  = frame_payload[280 +: 128];
    wire p1 = set_pres_a > 1 || (!set_pres_a && set_val_a != 0);

    // ---------------------------------------------------------------------
    // P2 -- DEREF arm, :879-885 (reads) / :892-894 (predicate)
    // ---------------------------------------------------------------------
    wire [7:0]   deref_pres_a = frame_payload[26*8 +: 8];
    wire [127:0] deref_val_a  = frame_payload[216 +: 128];
    wire [7:0]   deref_pres_b = frame_payload[47*8 +: 8];
    wire [127:0] deref_val_b  = frame_payload[384 +: 128];
    wire [7:0]   deref_pres_c = frame_payload[64*8 +: 8];
    wire [127:0] deref_val_c  = frame_payload[520 +: 128];
    wire p2 = deref_pres_a > 1 || deref_pres_b > 1 || deref_pres_c > 1 ||
              (!deref_pres_a && deref_val_a != 0) ||
              (!deref_pres_b && deref_val_b != 0) ||
              (!deref_pres_c && deref_val_c != 0);

    // ---------------------------------------------------------------------
    // P3 / P4 -- JUMP arm, :913-923 (reads) / :927-930 and :936 (predicates)
    // ---------------------------------------------------------------------
    wire [7:0]   jump_pres_a  = frame_payload[26*8 +: 8];
    wire [127:0] jump_val_a   = frame_payload[216 +: 128];
    wire [7:0]   jump_pres_b  = frame_payload[43*8 +: 8];
    wire [127:0] jump_val_b   = frame_payload[352 +: 128];
    wire [7:0]   jump_pres_c  = frame_payload[60*8 +: 8];
    wire [127:0] jump_val_c   = frame_payload[488 +: 128];
    wire [7:0]   jump_inv_present = frame_payload[86*8 +: 8];
    wire [127:0] jump_inv_value   = frame_payload[696 +: 128];
    wire [7:0]   taken_proposal   = frame_payload[77*8 +: 8];
    wire p3 = jump_pres_a > 1 || jump_pres_b > 1 || jump_pres_c > 1 ||
              (!jump_pres_a && jump_val_a != 0) ||
              (!jump_pres_b && jump_val_b != 0) ||
              (!jump_pres_c && jump_val_c != 0) ||
              jump_inv_present > 1 ||
              (!jump_inv_present && jump_inv_value != 0);
    wire p4 = taken_proposal > 1;

    // ---------------------------------------------------------------------
    // P5 -- XOR/MUL catch-all arm, :968-975 (reads) / :979-982 (predicate)
    // ---------------------------------------------------------------------
    wire [7:0]   alu_pres_a = frame_payload[26*8 +: 8];
    wire [127:0] alu_val_a  = frame_payload[216 +: 128];
    wire [7:0]   alu_pres_b = frame_payload[43*8 +: 8];
    wire [127:0] alu_val_b  = frame_payload[352 +: 128];
    wire [7:0]   alu_pres_c = frame_payload[60*8 +: 8];
    wire [127:0] alu_val_c  = frame_payload[488 +: 128];
    wire [7:0]   alu_inv_present =
        frame_opcode == OP_MUL ? frame_payload[77*8 +: 8] : 8'd0;
    wire [127:0] alu_inv_value =
        frame_opcode == OP_MUL ? frame_payload[624 +: 128] : 128'd0;
    wire p5 = alu_pres_a > 1 || alu_pres_b > 1 || alu_pres_c > 1 ||
              (!alu_pres_a && alu_val_a != 0) ||
              (!alu_pres_b && alu_val_b != 0) ||
              (!alu_pres_c && alu_val_c != 0) ||
              alu_inv_present > 1 ||
              (!alu_inv_present && alu_inv_value != 0);

    // ---------------------------------------------------------------------
    // A violation is a frame the validator ACCEPTS (so the decode ladder is
    // entered) that would still have tripped the inline predicate S11 deletes.
    // ---------------------------------------------------------------------
    assign viol_set       = !request_reject && arm_set   && p1;
    assign viol_deref     = !request_reject && arm_deref && p2;
    assign viol_jump_cell = !request_reject && arm_jump  && p3;
    assign viol_jump_prop = !request_reject && arm_jump  && p4;
    assign viol_alu       = !request_reject && arm_alu   && p5;
    assign viol_any = viol_set | viol_deref | viol_jump_cell |
                      viol_jump_prop | viol_alu;
endmodule

// Proof harness.  SEL picks which obligation is asserted so that the aggregate
// and each individual predicate can be discharged as separate SAT problems:
//   SEL=0 viol_any   SEL=1 viol_set   SEL=2 viol_deref
//   SEL=3 viol_jump_cell   SEL=4 viol_jump_prop   SEL=5 viol_alu
//
// Free input space = 8 + 16 + 1520 + 1 + 1 + 1 = 1547 bits.  No constraints, no
// assumptions and no abstraction are applied to any of them.
module probe_top #(
    parameter integer SEL = 0
) (
    input  wire [7:0]    frame_opcode,
    input  wire [15:0]   frame_length,
    input  wire [1519:0] frame_payload,
    input  wire          result_pending,
    input  wire          blake_result_pending,
    input  wire          blake_service_pending
);
    wire viol_set, viol_deref, viol_jump_cell, viol_jump_prop, viol_alu, viol_any;

    dominance_probe probe (
        .frame_opcode(frame_opcode),
        .frame_length(frame_length),
        .frame_payload(frame_payload),
        .result_pending(result_pending),
        .blake_result_pending(blake_result_pending),
        .blake_service_pending(blake_service_pending),
        .viol_set(viol_set),
        .viol_deref(viol_deref),
        .viol_jump_cell(viol_jump_cell),
        .viol_jump_prop(viol_jump_prop),
        .viol_alu(viol_alu),
        .viol_any(viol_any)
    );

    generate
        if (SEL == 0) begin : g_any
            always @* assert (viol_any == 1'b0);
        end else if (SEL == 1) begin : g_set
            always @* assert (viol_set == 1'b0);
        end else if (SEL == 2) begin : g_deref
            always @* assert (viol_deref == 1'b0);
        end else if (SEL == 3) begin : g_jump_cell
            always @* assert (viol_jump_cell == 1'b0);
        end else if (SEL == 4) begin : g_jump_prop
            always @* assert (viol_jump_prop == 1'b0);
        end else if (SEL == 5) begin : g_alu
            always @* assert (viol_alu == 1'b0);
        end
    endgenerate
endmodule

`default_nettype wire

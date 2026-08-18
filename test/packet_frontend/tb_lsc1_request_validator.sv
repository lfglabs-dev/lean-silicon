`default_nettype none

// Independent behavioural reference for the static request admission check.
// The DUT names one localparam per cell offset and unrolls the BLAKE3 group with
// a generate loop; this reference instead carries a per-opcode offset table and
// walks it, so a structural mutation of the DUT cannot be mirrored here.  The
// priority chain is restated in full because the order of the arms is the
// specified behaviour, not an implementation choice.
module lsc1_request_validator_golden (
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
    reg [255:0] cell_at;
    integer cell_count, k, at;
    reg known_opcode, cells_bad;
    reg [15:0] want_length;
    reg [7:0] present;
    reg [127:0] value;

    always @(*) begin
        reject = 1'b0;
        fault_status = 8'd0;
        fault_txn = 32'd0;
        fault_detail = 8'd0;
        known_opcode = 1'b1;
        want_length = 16'd0;
        cell_count = 0;
        cell_at = 256'd0;
        case (frame_opcode)
            8'h01: begin
                want_length = 16'd77;
                cell_at[0*32 +: 32] = 26; cell_at[1*32 +: 32] = 43;
                cell_at[2*32 +: 32] = 60; cell_count = 3;
            end
            8'h02: begin
                want_length = 16'd94;
                cell_at[0*32 +: 32] = 26; cell_at[1*32 +: 32] = 43;
                cell_at[2*32 +: 32] = 60; cell_at[3*32 +: 32] = 77; cell_count = 4;
            end
            8'h03: begin
                want_length = 16'd51;
                cell_at[0*32 +: 32] = 34; cell_count = 1;
            end
            8'h04, 8'h05, 8'h06: begin
                want_length = 16'd81;
                cell_at[0*32 +: 32] = 26; cell_at[1*32 +: 32] = 47;
                cell_at[2*32 +: 32] = 64; cell_count = 3;
            end
            8'h07: begin
                want_length = 16'd103;
                cell_at[0*32 +: 32] = 26; cell_at[1*32 +: 32] = 43;
                cell_at[2*32 +: 32] = 60; cell_at[3*32 +: 32] = 86; cell_count = 4;
            end
            8'h08: begin
                want_length = 16'd190;
                for (k = 0; k < 8; k = k + 1) cell_at[k*32 +: 32] = 54 + 17*k;
                cell_count = 8;
            end
            default: known_opcode = 1'b0;
        endcase

        cells_bad = 1'b0;
        for (k = 0; k < cell_count; k = k + 1) begin
            at = cell_at[k*32 +: 32];
            present = frame_payload[at*8 +: 8];
            value = frame_payload[(at + 1)*8 +: 128];
            if (present > 8'd1 || (present == 8'd0 && value != 128'd0)) cells_bad = 1'b1;
        end

        if (!known_opcode) begin
            reject = 1'b1; fault_status = 8'h82;
        end else if (frame_length != want_length) begin
            reject = 1'b1; fault_status = 8'h83;
            fault_txn = frame_payload[0 +: 32]; fault_detail = 8'd2;
        end else if (frame_payload[12*8 +: 8] > 8'd1) begin
            reject = 1'b1; fault_status = 8'h86;
        end else if (frame_payload[13*8 +: 8] != 8'd0) begin
            reject = 1'b1; fault_status = 8'h85; fault_detail = 8'd1;
        end else if (cells_bad) begin
            reject = 1'b1; fault_status = 8'h88;
        end else if (frame_opcode == 8'h07 && frame_payload[77*8 +: 8] > 8'd1) begin
            reject = 1'b1; fault_status = 8'h8f; fault_detail = 8'd3;
        end else if (result_pending || blake_result_pending || blake_service_pending) begin
            reject = 1'b1; fault_status = 8'h87; fault_txn = frame_payload[0 +: 32];
        end
    end
endmodule

module tb_lsc1_request_validator;
    reg [7:0] opcode;
    reg [15:0] length;
    reg [1519:0] payload;
    reg pend_result, pend_blake_result, pend_blake_service;

    wire dut_reject, gold_reject;
    wire [7:0] dut_status, dut_detail, gold_status, gold_detail;
    wire [31:0] dut_txn, gold_txn;

    integer directed_hits, trial, seed, i, at;
    integer seen_accept, seen_opcode, seen_length, seen_profile;
    integer seen_flags, seen_cell, seen_proposal, seen_state;
    integer probe_at [0:17];

    lsc1_request_validator dut (
        .frame_opcode(opcode), .frame_length(length), .frame_payload(payload),
        .result_pending(pend_result), .blake_result_pending(pend_blake_result),
        .blake_service_pending(pend_blake_service),
        .reject(dut_reject), .fault_status(dut_status),
        .fault_txn(dut_txn), .fault_detail(dut_detail)
    );

    lsc1_request_validator_golden golden (
        .frame_opcode(opcode), .frame_length(length), .frame_payload(payload),
        .result_pending(pend_result), .blake_result_pending(pend_blake_result),
        .blake_service_pending(pend_blake_service),
        .reject(gold_reject), .fault_status(gold_status),
        .fault_txn(gold_txn), .fault_detail(gold_detail)
    );

    // $random is signed, so the low bits are taken before the modulus.
    function [15:0] pick(input integer bound);
        begin
            pick = ($random(seed) & 32'h7fffffff) % bound;
        end
    endfunction

    function [15:0] good_length(input [7:0] op);
        begin
            case (op)
                8'h01: good_length = 16'd77;
                8'h02: good_length = 16'd94;
                8'h03: good_length = 16'd51;
                8'h04, 8'h05, 8'h06: good_length = 16'd81;
                8'h07: good_length = 16'd103;
                8'h08: good_length = 16'd190;
                default: good_length = 16'd0;
            endcase
        end
    endfunction

    // A frame that every arm of the chain accepts: right length, profile 0,
    // flags 0, every cell absent and zero, nothing outstanding.
    task clean(input [7:0] op);
        begin
            opcode = op;
            length = good_length(op);
            payload = 1520'b0;
            pend_result = 1'b0;
            pend_blake_result = 1'b0;
            pend_blake_service = 1'b0;
        end
    endtask

    task put_byte(input integer byte_at, input [7:0] value);
        begin
            payload[byte_at*8 +: 8] = value;
        end
    endtask

    task put_cell(input integer byte_at, input [7:0] present, input [127:0] value);
        begin
            payload[byte_at*8 +: 8] = present;
            payload[(byte_at + 1)*8 +: 128] = value;
        end
    endtask

    // Both the hand-written expectation and the reference are checked, so the
    // reference cannot silently drift into agreement with a broken DUT.
    task check(input [255:0] name, input exp_reject, input [7:0] exp_status,
               input [31:0] exp_txn, input [7:0] exp_detail);
        begin
            #1;
            if (gold_reject !== exp_reject || gold_status !== exp_status ||
                gold_txn !== exp_txn || gold_detail !== exp_detail)
                $fatal(1, "%0s: reference disagrees with the stated expectation got=%b/%02x/%08x/%02x expected=%b/%02x/%08x/%02x",
                       name, gold_reject, gold_status, gold_txn, gold_detail,
                       exp_reject, exp_status, exp_txn, exp_detail);
            if (dut_reject !== exp_reject || dut_status !== exp_status ||
                dut_txn !== exp_txn || dut_detail !== exp_detail)
                $fatal(1, "%0s: got=%b/%02x/%08x/%02x expected=%b/%02x/%08x/%02x",
                       name, dut_reject, dut_status, dut_txn, dut_detail,
                       exp_reject, exp_status, exp_txn, exp_detail);
            directed_hits = directed_hits + 1;
        end
    endtask

    initial begin
        directed_hits = 0;

        // Every compute opcode has an accepting frame, so a DUT that rejected
        // everything would not survive the first eight vectors.
        clean(8'h01); check("xor_clean", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h02); check("mul_clean", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h03); check("set_clean", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h04); check("deref_cell_clean", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h05); check("deref_pc_clean", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h06); check("deref_fp_clean", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h07); check("jump_clean", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h08); check("blake3_clean", 1'b0, 8'h00, 32'd0, 8'd0);

        // Unknown opcodes fault first and never carry the payload transaction id,
        // including the two that bracket the compute range.
        clean(8'h01); opcode = 8'h00; payload[0 +: 32] = 32'hdeadbeef;
        check("opcode_zero", 1'b1, 8'h82, 32'd0, 8'd0);
        clean(8'h01); opcode = 8'h09; length = 16'd77; payload[0 +: 32] = 32'hdeadbeef;
        check("opcode_nine", 1'b1, 8'h82, 32'd0, 8'd0);
        clean(8'h01); opcode = 8'hff; length = 16'd77;
        check("opcode_ff", 1'b1, 8'h82, 32'd0, 8'd0);

        // A bad opcode outranks everything below it, pending state included.
        clean(8'h01); opcode = 8'h09; put_byte(12, 8'd7); put_byte(13, 8'd1);
        pend_result = 1'b1;
        check("opcode_outranks_the_rest", 1'b1, 8'h82, 32'd0, 8'd0);

        // Length faults carry the payload transaction id and detail 2.
        clean(8'h01); length = 16'd76; payload[0 +: 32] = 32'h11223344;
        check("xor_length_short", 1'b1, 8'h83, 32'h11223344, 8'd2);
        clean(8'h01); length = 16'd78;
        check("xor_length_long", 1'b1, 8'h83, 32'd0, 8'd2);
        clean(8'h02); length = 16'd93; check("mul_length", 1'b1, 8'h83, 32'd0, 8'd2);
        clean(8'h03); length = 16'd50; check("set_length", 1'b1, 8'h83, 32'd0, 8'd2);
        clean(8'h04); length = 16'd80; check("deref_cell_length", 1'b1, 8'h83, 32'd0, 8'd2);
        clean(8'h05); length = 16'd82; check("deref_pc_length", 1'b1, 8'h83, 32'd0, 8'd2);
        clean(8'h06); length = 16'd0;  check("deref_fp_length", 1'b1, 8'h83, 32'd0, 8'd2);

        // The JUMP and BLAKE3 length constants are pinned from both sides: the
        // neighbouring value must fault and the stated value must not.
        clean(8'h07); length = 16'd102; check("jump_length_102", 1'b1, 8'h83, 32'd0, 8'd2);
        clean(8'h07); length = 16'd103; check("jump_length_103", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h08); length = 16'd189; check("blake_length_189", 1'b1, 8'h83, 32'd0, 8'd2);
        clean(8'h08); length = 16'd190; check("blake_length_190", 1'b0, 8'h00, 32'd0, 8'd0);

        // Profile and flags: the boundary value, the faulting value, and the
        // status and detail each arm is required to report.
        clean(8'h01); put_byte(12, 8'd1); check("profile_one_ok", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h01); put_byte(12, 8'd2); check("profile_two", 1'b1, 8'h86, 32'd0, 8'd0);
        clean(8'h01); put_byte(12, 8'hff); check("profile_ff", 1'b1, 8'h86, 32'd0, 8'd0);
        clean(8'h01); put_byte(13, 8'd1); check("flags_one", 1'b1, 8'h85, 32'd0, 8'd1);
        clean(8'h01); put_byte(13, 8'hff); check("flags_ff", 1'b1, 8'h85, 32'd0, 8'd1);

        // Priority between neighbouring arms, checked pairwise.
        clean(8'h01); length = 16'd76; put_byte(12, 8'd2); payload[0 +: 32] = 32'h55667788;
        check("length_outranks_profile", 1'b1, 8'h83, 32'h55667788, 8'd2);
        clean(8'h01); put_byte(12, 8'd2); put_byte(13, 8'd1);
        check("profile_outranks_flags", 1'b1, 8'h86, 32'd0, 8'd0);
        clean(8'h01); put_byte(13, 8'd1); put_cell(26, 8'd2, 128'd0);
        check("flags_outranks_cells", 1'b1, 8'h85, 32'd0, 8'd1);

        // The cell predicate: presence above one, and absent-but-non-zero.  Both
        // halves are required; either one alone would let the other through.
        clean(8'h03); put_cell(34, 8'd2, 128'd0);
        check("set_cell_present_two", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h03); put_cell(34, 8'd0, 128'd1);
        check("set_cell_absent_non_zero", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h03); put_cell(34, 8'd1, 128'd0);
        check("set_cell_present_zero_ok", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h03); put_cell(34, 8'd0, 128'd0);
        check("set_cell_absent_zero_ok", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h03); put_cell(34, 8'd1, {1'b1, 127'd0});
        check("set_cell_present_high_bit_ok", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h03); put_cell(34, 8'd0, {1'b1, 127'd0});
        check("set_cell_top_value_bit_counts", 1'b1, 8'h88, 32'd0, 8'd0);

        // Each DEREF cell offset individually, and the byte that sits between two
        // of them, which is the base index and must not be scanned as a cell.
        clean(8'h04); put_cell(26, 8'd0, 128'd1);
        check("deref_cell_26", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h04); put_cell(47, 8'd0, 128'd1);
        check("deref_cell_47", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h04); put_cell(64, 8'd0, 128'd1);
        check("deref_cell_64", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h04);
        put_byte(43, 8'hff); put_byte(44, 8'hff); put_byte(45, 8'hff); put_byte(46, 8'hff);
        check("deref_base_index_bytes_are_not_a_cell", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h05); put_cell(47, 8'd2, 128'd0);
        check("deref_pc_cell_47", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h06); put_cell(64, 8'd2, 128'd0);
        check("deref_fp_cell_64", 1'b1, 8'h88, 32'd0, 8'd0);

        // ALU cells, including the fourth one that only MUL carries.
        clean(8'h01); put_cell(26, 8'd2, 128'd0); check("xor_cell_26", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h01); put_cell(43, 8'd2, 128'd0); check("xor_cell_43", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h01); put_cell(60, 8'd2, 128'd0); check("xor_cell_60", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h01); put_cell(77, 8'd2, 128'hffff);
        check("xor_has_no_fourth_cell", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h02); put_cell(77, 8'd2, 128'd0); check("mul_cell_77", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h02); put_cell(60, 8'd0, 128'd1); check("mul_cell_60", 1'b1, 8'h88, 32'd0, 8'd0);

        // JUMP cells.  Offset 43 is a cell here even though the same byte is the
        // base index for DEREF, and offset 86 is the fourth cell.
        clean(8'h07); put_cell(26, 8'd2, 128'd0); check("jump_cell_26", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h07); put_cell(43, 8'd2, 128'd0); check("jump_cell_43", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h07); put_byte(78, 8'hff); put_byte(85, 8'hff);
        check("jump_bytes_between_proposal_and_last_cell_ignored", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h07); put_cell(60, 8'd0, 128'd1); check("jump_cell_60", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h07); put_cell(86, 8'd0, 128'd1); check("jump_cell_86", 1'b1, 8'h88, 32'd0, 8'd0);

        // All eight BLAKE3 cells sit on the 54 + 17i lattice.  Each one is checked,
        // and so is a byte on the 54 + 16i lattice that must not be scanned.
        for (i = 0; i < 8; i = i + 1) begin
            clean(8'h08);
            put_cell(54 + 17*i, 8'd2, 128'd0);
            check({"blake_cell_", 8'h30 + i[7:0]}, 1'b1, 8'h88, 32'd0, 8'd0);
        end
        // The eight cells tile bytes 54..189 without a gap, so no single byte lies
        // outside every cell.  Marking all eight present frees their values, and a
        // byte on the 54 + 16i lattice then decides: it is a value byte here, and a
        // presence byte for a scan that walked the wrong stride.
        clean(8'h08);
        for (i = 0; i < 8; i = i + 1) put_byte(54 + 17*i, 8'd1);
        check("blake_present_cells_have_free_values", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h08);
        for (i = 0; i < 8; i = i + 1) put_byte(54 + 17*i, 8'd1);
        put_byte(70, 8'd2);
        check("blake_stride_is_seventeen", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h08); put_cell(173, 8'd0, 128'd1);
        check("blake_last_cell_is_scanned", 1'b1, 8'h88, 32'd0, 8'd0);

        // The branch proposal byte belongs to JUMP alone.
        clean(8'h07); put_byte(77, 8'd1); check("jump_proposal_one_ok", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h07); put_byte(77, 8'd2); check("jump_proposal_two", 1'b1, 8'h8f, 32'd0, 8'd3);
        clean(8'h04); put_byte(64, 8'd1); put_byte(77, 8'd2);
        check("deref_has_no_proposal", 1'b0, 8'h00, 32'd0, 8'd0);
        clean(8'h03); put_byte(77, 8'd2); check("set_has_no_proposal", 1'b0, 8'h00, 32'd0, 8'd0);

        // LSC1-08 R10, pinned and deliberately not fixed by this slice.  A JUMP
        // frame that is both malformed in its fourth cell and carries an
        // out-of-range branch proposal reports BAD_CELL, not BAD_BRANCH_PROPOSAL.
        // The executable model orders these two the other way round; that
        // divergence is tracked as its own ticket and must not be repaired here,
        // so this vector lives in the RTL-versus-RTL lane only and is never
        // asserted against the model in the differential suite.
        clean(8'h07); put_byte(77, 8'd2); put_cell(86, 8'd0, 128'd1);
        check("r10_cell_scan_outranks_branch_proposal", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h07); put_byte(77, 8'd2); put_cell(26, 8'd2, 128'd0);
        check("r10_first_cell_also_outranks_proposal", 1'b1, 8'h88, 32'd0, 8'd0);

        // Pending state is the last arm.  It reports the payload transaction id,
        // and each of the three pending inputs reaches it on its own.
        clean(8'h01); pend_result = 1'b1; payload[0 +: 32] = 32'h0badf00d;
        check("result_pending", 1'b1, 8'h87, 32'h0badf00d, 8'd0);
        clean(8'h01); pend_blake_result = 1'b1;
        check("blake_result_pending", 1'b1, 8'h87, 32'd0, 8'd0);
        clean(8'h01); pend_blake_service = 1'b1;
        check("blake_service_pending", 1'b1, 8'h87, 32'd0, 8'd0);

        // A malformed frame is rejected on its contents even while a result is
        // outstanding: the contents arms all outrank the pending arm.
        clean(8'h01); pend_result = 1'b1; put_cell(26, 8'd2, 128'd0);
        payload[0 +: 32] = 32'h0badf00d;
        check("cells_outrank_pending_state", 1'b1, 8'h88, 32'd0, 8'd0);
        clean(8'h07); pend_blake_service = 1'b1; put_byte(77, 8'd2);
        check("proposal_outranks_pending_state", 1'b1, 8'h8f, 32'd0, 8'd3);
        clean(8'h01); pend_result = 1'b1; put_byte(13, 8'd1);
        check("flags_outrank_pending_state", 1'b1, 8'h85, 32'd0, 8'd1);
        clean(8'h01); pend_result = 1'b1; length = 16'd76; payload[0 +: 32] = 32'h0badf00d;
        check("length_outranks_pending_state", 1'b1, 8'h83, 32'h0badf00d, 8'd2);

        if (directed_hits != 78)
            $fatal(1, "expected 78 directed vectors, ran %0d", directed_hits);

        // Constrained randomisation over the byte offsets that any arm reads, plus
        // the neighbouring offsets a shifted or restrided scan would touch.  Each
        // trial starts from an accepting frame and disturbs one offset, so the
        // deeper arms are reached often instead of being masked by an earlier
        // fault on every draw.
        probe_at[0] = 26;  probe_at[1] = 34;  probe_at[2] = 43;  probe_at[3] = 44;
        probe_at[4] = 47;  probe_at[5] = 54;  probe_at[6] = 60;  probe_at[7] = 64;
        probe_at[8] = 70;  probe_at[9] = 71;  probe_at[10] = 77; probe_at[11] = 86;
        probe_at[12] = 88; probe_at[13] = 105; probe_at[14] = 122; probe_at[15] = 139;
        probe_at[16] = 156; probe_at[17] = 173;

        seen_accept = 0; seen_opcode = 0; seen_length = 0; seen_profile = 0;
        seen_flags = 0; seen_cell = 0; seen_proposal = 0; seen_state = 0;
        seed = 32'd20260818;
        for (trial = 0; trial < 6000; trial = trial + 1) begin
            payload = 1520'b0;
            opcode = (pick(5) == 0) ? pick(11) : 8'h01 + pick(8);
            length = (pick(10) < 7) ? good_length(opcode)
                                    : good_length(opcode) + 16'd1 - pick(3);
            payload[0 +: 32] = $random(seed);
            put_byte(12, (pick(4) == 0) ? pick(4) : 8'd0);
            put_byte(13, (pick(4) == 0) ? pick(4) : 8'd0);
            i = pick(20);
            if (i < 18) begin
                at = probe_at[i];
                put_cell(at, pick(4), (pick(2) == 0) ? 128'd0 : 128'd1);
            end
            put_byte(77, (pick(2) == 0) ? 8'd0 : pick(3));
            pend_result = (pick(4) == 0);
            pend_blake_result = (pick(4) == 0);
            pend_blake_service = (pick(4) == 0);
            #1;
            if (dut_reject !== gold_reject || dut_status !== gold_status ||
                dut_txn !== gold_txn || dut_detail !== gold_detail)
                $fatal(1, "random trial %0d op=%02x len=%0d: got=%b/%02x/%08x/%02x expected=%b/%02x/%08x/%02x",
                       trial, opcode, length, dut_reject, dut_status, dut_txn, dut_detail,
                       gold_reject, gold_status, gold_txn, gold_detail);
            if (!dut_reject) seen_accept = seen_accept + 1;
            else case (dut_status)
                8'h82: seen_opcode = seen_opcode + 1;
                8'h83: seen_length = seen_length + 1;
                8'h86: seen_profile = seen_profile + 1;
                8'h85: seen_flags = seen_flags + 1;
                8'h88: seen_cell = seen_cell + 1;
                8'h8f: seen_proposal = seen_proposal + 1;
                8'h87: seen_state = seen_state + 1;
                default: $fatal(1, "random trial %0d produced unreachable status %02x",
                                trial, dut_status);
            endcase
        end

        // Without this a degenerate random domain that never reached an arm would
        // still report a pass, and the random lane would prove nothing about it.
        if (seen_accept < 20 || seen_opcode < 20 || seen_length < 20 ||
            seen_profile < 20 || seen_flags < 20 || seen_cell < 20 ||
            seen_proposal < 20 || seen_state < 20)
            $fatal(1, "random lane left an arm under-exercised accept=%0d opcode=%0d length=%0d profile=%0d flags=%0d cell=%0d proposal=%0d state=%0d",
                   seen_accept, seen_opcode, seen_length, seen_profile,
                   seen_flags, seen_cell, seen_proposal, seen_state);

        $display("PASS: %0d directed request-validator vectors and 6000 constrained random trials (accept=%0d opcode=%0d length=%0d profile=%0d flags=%0d cell=%0d proposal=%0d state=%0d)",
                 directed_hits, seen_accept, seen_opcode, seen_length, seen_profile,
                 seen_flags, seen_cell, seen_proposal, seen_state);
        $finish;
    end
endmodule

`default_nettype wire

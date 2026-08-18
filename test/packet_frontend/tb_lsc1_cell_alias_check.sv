`default_nettype none

// Independent behavioural reference for the three-cell alias precheck.  The
// reference indexes frame_payload with raw bit numbers and selects the layout
// with an opcode `case`, rather than sharing the DUT's byte-offset localparams
// and `is_deref` multiplexers, so a structural mutation of the DUT cannot be
// mirrored by the reference.
module lsc1_cell_alias_check_golden (
    input  wire [7:0]   frame_opcode,
    input  wire [647:0] frame_payload,
    output reg          alias_inconsistent
);
    integer gi, gj;
    reg [31:0] addr [0:2];
    reg [7:0] pres [0:2];
    reg [127:0] vals [0:2];
    reg active;

    // Explicit sensitivity list rather than @*: the array writes below would
    // otherwise make the block sensitive to its own array reads.
    always @(frame_opcode or frame_payload) begin
        addr[0] = 32'd0; addr[1] = 32'd0; addr[2] = 32'd0;
        pres[0] = 8'd0; pres[1] = 8'd0; pres[2] = 8'd0;
        vals[0] = 128'd0; vals[1] = 128'd0; vals[2] = 128'd0;
        active = 1'b0;
        case (frame_opcode)
            // DEREF_CELL / DEREF_PC / DEREF_FP: cells at bytes 26, 47, 64 and
            // the middle address formed from base_index (byte 43), not fp.
            8'h04, 8'h05, 8'h06: begin
                active = 1'b1;
                addr[0] = frame_payload[64 +: 32] + frame_payload[112 +: 32];
                addr[1] = frame_payload[344 +: 32] + frame_payload[144 +: 32];
                addr[2] = frame_payload[64 +: 32] + frame_payload[176 +: 32];
                pres[0] = frame_payload[208 +: 8];
                vals[0] = frame_payload[216 +: 128];
                pres[1] = frame_payload[376 +: 8];
                vals[1] = frame_payload[384 +: 128];
                pres[2] = frame_payload[512 +: 8];
                vals[2] = frame_payload[520 +: 128];
            end
            // JUMP / XOR / MUL: cells at bytes 26, 43, 60, every address from fp.
            8'h07, 8'h01, 8'h02: begin
                active = 1'b1;
                addr[0] = frame_payload[64 +: 32] + frame_payload[112 +: 32];
                addr[1] = frame_payload[64 +: 32] + frame_payload[144 +: 32];
                addr[2] = frame_payload[64 +: 32] + frame_payload[176 +: 32];
                pres[0] = frame_payload[208 +: 8];
                vals[0] = frame_payload[216 +: 128];
                pres[1] = frame_payload[344 +: 8];
                vals[1] = frame_payload[352 +: 128];
                pres[2] = frame_payload[480 +: 8];
                vals[2] = frame_payload[488 +: 128];
            end
            default: active = 1'b0;
        endcase

        alias_inconsistent = 1'b0;
        if (active)
            for (gi = 0; gi < 3; gi = gi + 1)
                for (gj = 0; gj < 3; gj = gj + 1)
                    if (gj > gi && addr[gi] == addr[gj] &&
                        (pres[gi] != pres[gj] || vals[gi] != vals[gj]))
                        alias_inconsistent = 1'b1;
    end
endmodule

module tb_lsc1_cell_alias_check;
    localparam [7:0] OP_XOR = 8'h01, OP_MUL = 8'h02, OP_SET = 8'h03,
                     OP_DEREF_CELL = 8'h04, OP_DEREF_PC = 8'h05,
                     OP_DEREF_FP = 8'h06, OP_JUMP = 8'h07,
                     OP_BLAKE3 = 8'h08, OP_RETIRE = 8'h12;

    reg [7:0] opcode;
    reg [647:0] payload;
    wire dut_out, golden_out;
    integer directed_hits, random_hits, trial, seed, i;
    reg [7:0] random_opcode;

    lsc1_cell_alias_check dut (
        .frame_opcode(opcode),
        .frame_payload(payload),
        .alias_inconsistent(dut_out)
    );

    lsc1_cell_alias_check_golden golden (
        .frame_opcode(opcode),
        .frame_payload(payload),
        .alias_inconsistent(golden_out)
    );

    task put_u32(input integer at, input [31:0] v);
        begin
            payload[at*8 +: 32] = v;
        end
    endtask

    task put_cell(input integer at, input [7:0] p, input [127:0] v);
        begin
            payload[at*8 +: 8] = p;
            payload[(at + 1)*8 +: 128] = v;
        end
    endtask

    // fp/base_index and the three offsets are chosen so the derived addresses are
    // pairwise distinct and every cell carries a distinct value: the predicate
    // must be false until a vector deliberately collides two of them.
    task clean_deref(input [7:0] op);
        begin
            payload = 648'd0;
            opcode = op;
            put_u32(8, 32'd1000);
            put_u32(14, 32'd1);
            put_u32(18, 32'd2);
            put_u32(22, 32'd3);
            put_u32(43, 32'd5000);
            put_cell(26, 8'd1, 128'h11);
            put_cell(47, 8'd1, 128'h22);
            put_cell(64, 8'd1, 128'h33);
        end
    endtask

    task clean_scalar(input [7:0] op);
        begin
            payload = 648'd0;
            opcode = op;
            put_u32(8, 32'd1000);
            put_u32(14, 32'd1);
            put_u32(18, 32'd2);
            put_u32(22, 32'd3);
            put_cell(26, 8'd1, 128'h11);
            put_cell(43, 8'd1, 128'h22);
            put_cell(60, 8'd1, 128'h33);
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

        // ---- the three DEREF opcodes share one layout and one verdict ----
        clean_deref(OP_DEREF_CELL); check("deref_cell_clean", 1'b0);
        clean_deref(OP_DEREF_PC);   check("deref_pc_clean", 1'b0);
        clean_deref(OP_DEREF_FP);   check("deref_fp_clean", 1'b0);

        // a and b collide (base_index + off_b == fp + off_a) and disagree.
        clean_deref(OP_DEREF_CELL); put_u32(43, 32'd1000); put_u32(18, 32'd1);
        check("deref_ab_alias_disagree", 1'b1);

        // The same collision with cells that agree completely is consistent.
        clean_deref(OP_DEREF_CELL); put_u32(43, 32'd1000); put_u32(18, 32'd1);
        put_cell(47, 8'd1, 128'h11);
        check("deref_ab_alias_agree", 1'b0);

        // Same address, same value, different presence: the presence term decides.
        clean_deref(OP_DEREF_CELL); put_u32(43, 32'd1000); put_u32(18, 32'd1);
        put_cell(47, 8'd0, 128'h11);
        check("deref_present_term_required", 1'b1);

        // Same address, same presence, different value: the value term decides.
        clean_deref(OP_DEREF_CELL); put_u32(43, 32'd1000); put_u32(18, 32'd1);
        put_cell(47, 8'd1, 128'h99);
        check("deref_value_term_required", 1'b1);

        // a and c collide.
        clean_deref(OP_DEREF_CELL); put_u32(22, 32'd1);
        check("deref_ac_alias_disagree", 1'b1);

        // b and c collide and nothing else does: a predicate that drops the b-c
        // pair must miss this one.
        clean_deref(OP_DEREF_CELL); put_u32(43, 32'd1000); put_u32(18, 32'd3);
        check("deref_bc_alias_disagree", 1'b1);

        clean_deref(OP_DEREF_CELL); put_u32(43, 32'd1000); put_u32(18, 32'd3);
        put_cell(47, 8'd1, 128'h33);
        check("deref_bc_alias_agree", 1'b0);

        // The middle DEREF address is base_index + off_b.  Here fp + off_b would
        // collide with a while base_index + off_b does not, so a predicate that
        // used fp would invent a violation.
        clean_deref(OP_DEREF_CELL); put_u32(18, 32'd1);
        check("deref_addr_b_uses_base_index_not_fp", 1'b0);

        // The converse: base_index + off_b really does collide with a, and a
        // predicate that used fp would miss it.
        clean_deref(OP_DEREF_CELL); put_u32(43, 32'd900); put_u32(18, 32'd101);
        check("deref_addr_b_base_index_collision_seen", 1'b1);

        // DEREF cell b's presence byte sits at 47, not at 43 where base_index's
        // low byte lives.  base_index is picked so byte 43 is itself 8'd1 and a
        // predicate reading there would still see a plausible presence byte; the
        // shifted value window is what gives it away.
        clean_deref(OP_DEREF_CELL); put_u32(43, 32'd1); put_u32(18, 32'd1000);
        put_cell(47, 8'd1, 128'h11);
        check("deref_cell_b_at_47_not_43", 1'b0);

        // DEREF cell c sits at byte 64, not the scalar layout's byte 60.
        clean_deref(OP_DEREF_CELL); put_u32(22, 32'd1); put_cell(64, 8'd1, 128'h11);
        check("deref_cell_c_at_64_not_60", 1'b0);

        // Closure of the declared port width: cell c's value ends at byte 80, so
        // a difference confined to that byte must still be observed.
        clean_deref(OP_DEREF_CELL); put_u32(22, 32'd1);
        put_cell(64, 8'd1, {8'h01, 120'h11});
        check("deref_cell_c_value_top_byte", 1'b1);

        // Address arithmetic wraps: fp + off_a and fp + off_c both land on zero.
        clean_deref(OP_DEREF_CELL); put_u32(8, 32'hffffffff);
        put_u32(14, 32'd1); put_u32(22, 32'd1);
        check("deref_address_wraps_to_zero", 1'b1);

        // ---- JUMP, XOR and MUL share the other layout ----
        clean_scalar(OP_JUMP); check("jump_clean", 1'b0);
        clean_scalar(OP_XOR);  check("xor_clean", 1'b0);
        clean_scalar(OP_MUL);  check("mul_clean", 1'b0);

        clean_scalar(OP_JUMP); put_u32(18, 32'd1); check("jump_ab_alias_disagree", 1'b1);
        clean_scalar(OP_XOR);  put_u32(18, 32'd1); check("xor_ab_alias_disagree", 1'b1);
        clean_scalar(OP_MUL);  put_u32(18, 32'd1); check("mul_ab_alias_disagree", 1'b1);

        clean_scalar(OP_JUMP); put_u32(18, 32'd1); put_cell(43, 8'd1, 128'h11);
        check("jump_ab_alias_agree", 1'b0);

        clean_scalar(OP_JUMP); put_u32(18, 32'd1); put_cell(43, 8'd0, 128'h11);
        check("jump_present_term_required", 1'b1);

        clean_scalar(OP_JUMP); put_u32(18, 32'd1); put_cell(43, 8'd1, 128'h99);
        check("jump_value_term_required", 1'b1);

        clean_scalar(OP_JUMP); put_u32(22, 32'd1); check("jump_ac_alias_disagree", 1'b1);

        clean_scalar(OP_JUMP); put_u32(22, 32'd2); check("jump_bc_alias_disagree", 1'b1);

        // The scalar layout reads cell b's presence at byte 43.  The DEREF slot 47
        // lies *inside* this layout's cell-b value, so the disagreement cannot be
        // written there without destroying the cell; instead cell a and cell b are
        // made to agree exactly while carrying a value whose byte 47 is 8'h55.  A
        // predicate reading byte 47 takes that value byte for a presence byte.
        clean_scalar(OP_JUMP); put_u32(18, 32'd1);
        put_cell(26, 8'd1, 128'h55000011); put_cell(43, 8'd1, 128'h55000011);
        check("jump_cell_b_at_43_not_47", 1'b0);

        // ...and cell c's presence at byte 60, with the DEREF slot 64 landing
        // inside its value the same way.
        clean_scalar(OP_JUMP); put_u32(22, 32'd1);
        put_cell(26, 8'd1, 128'h55000011); put_cell(60, 8'd1, 128'h55000011);
        check("jump_cell_c_at_60_not_64", 1'b0);

        // All three cells on one address: the a-b pair agrees and only the a-c and
        // b-c pairs carry the disagreement.
        clean_scalar(OP_JUMP); put_u32(18, 32'd1); put_u32(22, 32'd1);
        put_cell(43, 8'd1, 128'h11);
        check("jump_three_way_alias_one_disagrees", 1'b1);

        clean_scalar(OP_JUMP); put_u32(18, 32'd1); put_u32(22, 32'd1);
        put_cell(43, 8'd1, 128'h11); put_cell(60, 8'd1, 128'h11);
        check("jump_three_way_alias_all_agree", 1'b0);

        clean_scalar(OP_MUL); put_u32(8, 32'hffffffff);
        put_u32(14, 32'd1); put_u32(22, 32'd1);
        check("mul_address_wraps_to_zero", 1'b1);

        // ---- opcodes outside the checked set are tied low ----
        // Each of these carries a payload that would be a violation under the
        // scalar layout, so a predicate that widened its opcode set would fire.
        clean_scalar(OP_SET); put_u32(18, 32'd1);
        check("set_is_not_checked", 1'b0);
        clean_scalar(OP_BLAKE3); put_u32(18, 32'd1);
        check("blake3_is_not_checked", 1'b0);
        clean_scalar(OP_RETIRE); put_u32(18, 32'd1);
        check("retire_is_not_checked", 1'b0);
        clean_scalar(8'h00); put_u32(18, 32'd1);
        check("opcode_zero_is_not_checked", 1'b0);
        clean_scalar(8'hff); put_u32(18, 32'd1);
        check("opcode_ff_is_not_checked", 1'b0);

        // Constrained randomisation: small address and value domains so that
        // collisions and agreements are frequent rather than astronomically rare.
        seed = 32'd20260818;
        for (trial = 0; trial < 6000; trial = trial + 1) begin
            case ($random(seed) & 32'h7)
                0: random_opcode = OP_XOR;
                1: random_opcode = OP_MUL;
                2: random_opcode = OP_SET;
                3: random_opcode = OP_DEREF_CELL;
                4: random_opcode = OP_DEREF_PC;
                5: random_opcode = OP_DEREF_FP;
                6: random_opcode = OP_JUMP;
                default: random_opcode = OP_BLAKE3;
            endcase
            payload = 648'd0;
            opcode = random_opcode;
            put_u32(8, $random(seed) & 32'h3);
            put_u32(14, $random(seed) & 32'h3);
            put_u32(18, $random(seed) & 32'h3);
            put_u32(22, $random(seed) & 32'h3);
            if (random_opcode == OP_DEREF_CELL || random_opcode == OP_DEREF_PC ||
                random_opcode == OP_DEREF_FP) begin
                put_u32(43, $random(seed) & 32'h3);
                put_cell(26, $random(seed) & 8'h3, $random(seed) & 128'h3);
                put_cell(47, $random(seed) & 8'h3, $random(seed) & 128'h3);
                put_cell(64, $random(seed) & 8'h3, $random(seed) & 128'h3);
            end else begin
                put_cell(26, $random(seed) & 8'h3, $random(seed) & 128'h3);
                put_cell(43, $random(seed) & 8'h3, $random(seed) & 128'h3);
                put_cell(60, $random(seed) & 8'h3, $random(seed) & 128'h3);
            end
            #1;
            if (dut_out !== golden_out)
                $fatal(1, "random trial %0d opcode=%02h: alias_inconsistent got=%b expected=%b",
                       trial, random_opcode, dut_out, golden_out);
            if (golden_out) random_hits = random_hits + 1;
        end

        if (directed_hits != 37)
            $fatal(1, "expected 37 directed vectors, ran %0d", directed_hits);
        // Guards against a degenerate random domain in which the predicate is
        // never true and the random lane would therefore prove nothing.
        if (random_hits < 200)
            $fatal(1, "random lane produced only %0d positive verdicts", random_hits);

        $display("PASS: %0d directed cell-alias vectors and 6000 constrained random trials (%0d positive)",
                 directed_hits, random_hits);
        $finish;
    end
endmodule

`default_nettype wire

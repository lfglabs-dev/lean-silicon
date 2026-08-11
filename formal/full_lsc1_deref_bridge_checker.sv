`default_nettype none

// Safety plus a dedicated accepted-DEREF-to-matching-RETIRE witness, bound
// inside the exact production lsc1_packet_frontend.
module full_lsc1_deref_bridge_checker (
    input wire clk, rst_n, abort, rx_valid, rx_ready, input wire [7:0] rx_data,
    input wire tx_valid, tx_ready, input wire [7:0] tx_data,
    input wire frame_valid, event_ready, input wire [7:0] frame_opcode,
    input wire [15:0] frame_length, input wire [2047:0] frame_payload,
    input wire tx_start, input wire [3:0] compute_state,
    input wire result_pending, capture_result_crc, input wire [31:0] staged_txn_id,
    input wire [31:0] staged_next_pc, staged_next_fp, staged_result_crc,
    input wire [31:0] committed_pc, committed_fp, retire_seq,
    input wire done_pulse
);
    reg past_valid, reset_seen;
    reg [31:0] expected_retire_seq;
    initial past_valid = 1'b0;
    initial reset_seen = 1'b0;
    initial expected_retire_seq = 32'b0;

    wire retire_accept = frame_valid && event_ready && frame_opcode == 8'h12 &&
        frame_length == 16'd8;
    wire retire_match = retire_accept && result_pending &&
        frame_payload[0 +: 32] == staged_txn_id &&
        frame_payload[32 +: 32] == staged_result_crc;

    always @(posedge clk) begin
        past_valid <= 1'b1;
        // One sampled reset edge initializes every production register.  Mark
        // that edge directly; delaying through past_valid needlessly inserted
        // a second reset cycle and put the quiescent witness one step beyond
        // the bound derived from the executable trace.
        reset_seen <= 1'b1;
        if (!rst_n)
            expected_retire_seq <= 32'b0;
        else if (!abort && retire_match)
            expected_retire_seq <= expected_retire_seq + 1'b1;
    end

    function automatic [31:0] crc_byte(input [31:0] crc_in, input [7:0] data);
        integer bit_index;
        reg [31:0] work;
        begin
            work = crc_in ^ data;
            for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1)
                work = work[0] ? ((work >> 1) ^ 32'hedb88320) : (work >> 1);
            crc_byte = work;
        end
    endfunction

`ifdef FORMAL_DEREF_REACHABILITY
    localparam [2:0] W_DEREF = 0, W_RESULT = 1, W_CRC = 2,
                     W_RETIRE = 3, W_DONE = 4, W_QUIET = 5;
    reg [2:0] witness_phase;
    reg [6:0] deref_beat;
    reg [5:0] result_beat;
    reg [4:0] retire_beat;
    reg [31:0] emitted_result_crc_work, emitted_result_crc;
    reg [1:0] commit_updates;
    reg [1:0] done_count;
    initial witness_phase = W_DEREF;
    initial deref_beat = 0;
    initial result_beat = 0;
    initial retire_beat = 0;
    initial emitted_result_crc_work = 32'hffffffff;
    initial emitted_result_crc = 0;
    initial commit_updates = 0;
    initial done_count = 0;

    function automatic [7:0] deref_byte(input [6:0] beat);
        begin
            case (beat)
                0: deref_byte = 8'ha1; 1: deref_byte = 8'h01;
                2: deref_byte = 8'h04; 4: deref_byte = 8'h51;
                18: deref_byte = 8'h01;
                24: deref_byte = 8'h01; 28: deref_byte = 8'h02;
                32: deref_byte = 8'h01; 33: deref_byte = 8'h01;
                87: deref_byte = 8'hb0; 88: deref_byte = 8'h5f;
                89: deref_byte = 8'h6e; 90: deref_byte = 8'hf9;
                default: deref_byte = 8'h00;
            endcase
        end
    endfunction

    // Expected 35-byte RESULT payload for the concrete zero-state DEREF_CELL:
    // txn=0, next_pc=1, next_fp=0, no write, one deferred equality, three reads.
    function automatic [7:0] result_payload_byte(input [5:0] beat);
        begin
            case (beat)
                4: result_payload_byte = 8'h01;
                13: result_payload_byte = 8'h01;
                14: result_payload_byte = 8'h01;
                18: result_payload_byte = 8'h02;
                22: result_payload_byte = 8'h03;
                27: result_payload_byte = 8'h01;
                31: result_payload_byte = 8'h02;
                default: result_payload_byte = 8'h00;
            endcase
        end
    endfunction

    // CRC-32 of the complete expected RESULT envelope prefix (magic, version,
    // status, length, and payload).  This is deliberately derived from the
    // specified bytes rather than from tx_data or the packet TX's saved_crc.
    function automatic [31:0] result_envelope_crc;
        reg [31:0] work;
        integer i;
        begin
            work = 32'hffffffff;
            work = crc_byte(work, 8'h5a); work = crc_byte(work, 8'h01);
            work = crc_byte(work, 8'h00); work = crc_byte(work, 8'h23);
            work = crc_byte(work, 8'h00);
            for (i = 0; i < 35; i = i + 1)
                work = crc_byte(work, result_payload_byte(i));
            result_envelope_crc = ~work;
        end
    endfunction
    wire [31:0] expected_result_envelope_crc = result_envelope_crc();

    function automatic [31:0] retire_envelope_crc(input [31:0] payload_crc);
        reg [31:0] work;
        integer i;
        begin
            work = 32'hffffffff;
            work = crc_byte(work, 8'ha1); work = crc_byte(work, 8'h01);
            work = crc_byte(work, 8'h12); work = crc_byte(work, 8'h00);
            work = crc_byte(work, 8'h08); work = crc_byte(work, 8'h00);
            for (i = 0; i < 4; i = i + 1) work = crc_byte(work, 8'h00);
            for (i = 0; i < 4; i = i + 1)
                work = crc_byte(work, payload_crc[i*8 +: 8]);
            retire_envelope_crc = ~work;
        end
    endfunction

    function automatic [7:0] retire_byte(input [4:0] beat, input [31:0] payload_crc);
        reg [31:0] envelope_crc;
        begin
            envelope_crc = retire_envelope_crc(payload_crc);
            case (beat)
                0: retire_byte = 8'ha1; 1: retire_byte = 8'h01;
                2: retire_byte = 8'h12; 4: retire_byte = 8'h08;
                10: retire_byte = payload_crc[7:0];
                11: retire_byte = payload_crc[15:8];
                12: retire_byte = payload_crc[23:16];
                13: retire_byte = payload_crc[31:24];
                14: retire_byte = envelope_crc[7:0];
                15: retire_byte = envelope_crc[15:8];
                16: retire_byte = envelope_crc[23:16];
                17: retire_byte = envelope_crc[31:24];
                default: retire_byte = 8'h00;
            endcase
        end
    endfunction

    always @(posedge clk) begin
        if (!past_valid || !reset_seen) begin
            assume(!rst_n);
        end else begin
            assume(rst_n);
            assume(!abort);
            assume(tx_ready);
            if (witness_phase == W_DEREF) begin
                assume(rx_valid);
                assume(rx_data == deref_byte(deref_beat));
                if (rx_ready) begin
                    if (deref_beat == 90)
                        witness_phase <= W_RESULT;
                    else
                        deref_beat <= deref_beat + 1'b1;
                end
            end else if (witness_phase == W_RETIRE) begin
                assume(rx_valid);
                assume(rx_data == retire_byte(retire_beat, emitted_result_crc));
                if (rx_ready) begin
                    if (retire_beat == 17)
                        witness_phase <= W_DONE;
                    else
                        retire_beat <= retire_beat + 1'b1;
                end
            end else begin
                assume(!rx_valid);
            end
        end

        if (past_valid && reset_seen && witness_phase == W_RESULT && tx_valid && tx_ready) begin
            if (result_beat == 0) assert(tx_data == 8'h5a);
            else if (result_beat == 1) assert(tx_data == 8'h01);
            else if (result_beat == 2) assert(tx_data == 8'h00);
            else if (result_beat == 3) assert(tx_data == 8'h23);
            else if (result_beat == 4) assert(tx_data == 8'h00);
            else if (result_beat < 40) begin
                assert(tx_data == result_payload_byte(result_beat - 5));
                emitted_result_crc_work <= crc_byte(emitted_result_crc_work, tx_data);
                if (result_beat == 39)
                    emitted_result_crc <= ~crc_byte(emitted_result_crc_work, tx_data);
            end else if (result_beat == 40)
                assert(tx_data == expected_result_envelope_crc[7:0]);
            else if (result_beat == 41)
                assert(tx_data == expected_result_envelope_crc[15:8]);
            else if (result_beat == 42)
                assert(tx_data == expected_result_envelope_crc[23:16]);
            else if (result_beat == 43)
                assert(tx_data == expected_result_envelope_crc[31:24]);
            if (result_beat == 43) begin
                witness_phase <= W_CRC;
                assert(staged_txn_id == 0);
                assert(staged_next_pc == 1);
                assert(staged_next_fp == 0);
            end else
                result_beat <= result_beat + 1'b1;
        end

        // This binds the internal retirement check to CRC-32 of the emitted
        // RESULT payload, independently accumulated above.
        if (past_valid && reset_seen && witness_phase == W_CRC) begin
            if (!capture_result_crc) witness_phase <= W_RETIRE;
        end
        if (past_valid && reset_seen &&
            (witness_phase == W_CRC || witness_phase == W_RETIRE) &&
            !capture_result_crc)
            assert(staged_result_crc == emitted_result_crc);

        if (past_valid && reset_seen && retire_seq != $past(retire_seq))
            commit_updates <= commit_updates + 1'b1;
        if (past_valid && reset_seen && done_pulse)
            done_count <= done_count + 1'b1;

        if (past_valid && reset_seen) begin
            assert(commit_updates <= 1);
            assert(done_count <= 1);
            if (witness_phase == W_DONE && done_pulse) begin
                assert(commit_updates == 0); // counters update after this edge
                assert(done_count == 0);
                assert(retire_seq == 1);
                assert(committed_pc == 1 && committed_fp == 0);
                assert(!result_pending);
                witness_phase <= W_QUIET;
            end
            if (witness_phase == W_QUIET) begin
                assert(!done_pulse);
                assert(commit_updates == 1);
                assert(done_count == 1);
                assert(retire_seq == 1);
                assert(committed_pc == 1 && committed_fp == 0);
                assert(!result_pending);
            end
        end
        cover(witness_phase == W_QUIET && !done_pulse &&
              commit_updates == 1 && done_count == 1 && retire_seq == 1 &&
              committed_pc == 1 && committed_fp == 0 && !result_pending);
    end
`else
    // The arbitrary-traffic depth-20 safety task keeps no witness assumptions.
    always @(posedge clk)
        cover(rst_n && frame_valid && event_ready &&
              (frame_opcode == 8'h04 || frame_opcode == 8'h05 ||
               frame_opcode == 8'h06) && frame_length == 16'd81);
`endif

    always @(posedge clk) begin
        if (!past_valid || !reset_seen) assume(!rst_n);
        if (past_valid && reset_seen)
            assert(retire_seq == expected_retire_seq);
        if (past_valid && reset_seen)
            assert(done_pulse == ($past(rst_n) && !$past(abort) && $past(retire_match)));
        if (past_valid && reset_seen && $past(tx_valid && !tx_ready && rst_n && !abort)) begin
            assert(tx_valid); assert(tx_data == $past(tx_data));
        end
        if (past_valid && reset_seen && (!$past(rst_n) || $past(abort))) begin
            assert(!result_pending); assert(compute_state == 0);
            assert(!tx_start); assert(!done_pulse);
        end
        if (past_valid && reset_seen && $past(result_pending) && result_pending &&
            $past(rst_n) && !$past(abort)) begin
            assert(staged_txn_id == $past(staged_txn_id));
            assert(staged_next_pc == $past(staged_next_pc));
            assert(staged_next_fp == $past(staged_next_fp));
            if (!$past(capture_result_crc))
                assert(staged_result_crc == $past(staged_result_crc));
        end
        // The first post-reset value may differ from the arbitrary pre-reset
        // initial state.  Only classify deltas once both samples are known to
        // follow the sampled reset edge.
        if (past_valid && reset_seen && $past(reset_seen) &&
            retire_seq != $past(retire_seq)) begin
            assert($past(rst_n) && !$past(abort));
            assert(retire_seq == $past(retire_seq) + 1'b1);
            assert($past(retire_match)); assert(done_pulse); assert(!result_pending);
        end
        if (past_valid && reset_seen && done_pulse) begin
            assert(retire_seq == $past(retire_seq) + 1'b1);
            assert($past(retire_match));
        end
        if (past_valid && reset_seen && $past(done_pulse) && !$past(abort) && rst_n)
            assert(!done_pulse);
    end
endmodule

`default_nettype wire

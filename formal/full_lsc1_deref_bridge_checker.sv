`default_nettype none

// Bounded safety checker bound inside the exact authored packet frontend.
// Reachability is intentionally checked separately: covers are bounded witnesses.
module full_lsc1_deref_bridge_checker (
    input wire clk, rst_n, abort, rx_valid, rx_ready, input wire [7:0] rx_data,
    input wire tx_valid, tx_ready, input wire [7:0] tx_data,
    input wire frame_valid, event_ready, input wire [7:0] frame_opcode,
    input wire [15:0] frame_length, input wire [2047:0] frame_payload,
    input wire tx_start, input wire [3:0] compute_state,
    input wire result_pending, capture_result_crc, input wire [31:0] staged_txn_id,
    input wire [31:0] staged_next_pc, staged_next_fp, staged_result_crc,
    input wire [31:0] retire_seq, input wire done_pulse
);
    reg past_valid;
    reg reset_seen;
    reg [31:0] expected_retire_seq;
    initial past_valid = 1'b0;
    initial reset_seen = 1'b0;
    initial expected_retire_seq = 32'b0;
    always @(posedge clk) begin
        past_valid <= 1'b1;
        reset_seen <= past_valid;
        if (!rst_n)
            expected_retire_seq <= 32'b0;
        else if (!abort && retire_match)
            expected_retire_seq <= expected_retire_seq + 1'b1;
    end

    wire retire_accept = frame_valid && event_ready && frame_opcode == 8'h12 &&
        frame_length == 16'd8;
    wire retire_match = retire_accept && result_pending &&
        frame_payload[0 +: 32] == staged_txn_id &&
        frame_payload[32 +: 32] == staged_result_crc;

`ifdef FORMAL_DEREF_REACHABILITY
    // Concrete byte-exact witness: reset, then a valid 91-beat DEREF_CELL
    // envelope (81-byte payload, profile byte 1, IEEE CRC-32 0x58e32428).
    // Constraining only this cover task avoids asking the solver to discover a
    // CRC preimage; the safety task retains arbitrary inputs and backpressure.
    reg [6:0] witness_beat;
    initial witness_beat = 0;
    function automatic [7:0] witness_byte(input [6:0] beat);
        begin
            case (beat)
                0: witness_byte = 8'ha1;
                1: witness_byte = 8'h01;
                2: witness_byte = 8'h04;
                4: witness_byte = 8'h51;
                18: witness_byte = 8'h01;
                87: witness_byte = 8'h28;
                88: witness_byte = 8'h24;
                89: witness_byte = 8'he3;
                90: witness_byte = 8'h58;
                default: witness_byte = 8'h00;
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
            assume(rx_valid);
            assume(rx_data == witness_byte(witness_beat));
            if (rx_valid && rx_ready && witness_beat < 7'd91)
                witness_beat <= witness_beat + 1'b1;
        end
    end
`endif

    // Explicit non-vacuity obligation. A valid 81-byte DEREF needs 91 accepted
    // beats after reset before it can be presented to the controller.
    always @(posedge clk) begin
        cover(rst_n && frame_valid && event_ready &&
              (frame_opcode == 8'h04 || frame_opcode == 8'h05 ||
               frame_opcode == 8'h06) && frame_length == 16'd81);
    end

    always @(posedge clk) begin
        // Hold reset for the two formal startup states so assertions observe
        // the sequential reset assignment, not unconstrained pre-reset RTL.
        if (!past_valid || !reset_seen) assume(!rst_n);
        // Canonical reachable-state invariant: reset establishes sequence zero
        // and only an accepted, matching RETIRE advances it. This ghost state
        // records protocol history; it does not constrain environment inputs.
        if (past_valid && reset_seen)
            assert(retire_seq == expected_retire_seq);
        if (past_valid && reset_seen) begin
            assert(done_pulse == ($past(rst_n) && !$past(abort) &&
                                  $past(retire_match)));
        end
        if (past_valid && reset_seen && $past(tx_valid && !tx_ready && rst_n && !abort)) begin
            assert(tx_valid);
            assert(tx_data == $past(tx_data));
        end
        if (past_valid && reset_seen && (!$past(rst_n) || $past(abort))) begin
            assert(!result_pending);
            assert(compute_state == 4'd0);
            assert(!tx_start);
            assert(!done_pulse);
        end
        if (past_valid && reset_seen && $past(result_pending) && result_pending &&
            $past(rst_n) && !$past(abort)) begin
            assert(staged_txn_id == $past(staged_txn_id));
            assert(staged_next_pc == $past(staged_next_pc));
            assert(staged_next_fp == $past(staged_next_fp));
            if (!$past(capture_result_crc))
                assert(staged_result_crc == $past(staged_result_crc));
        end
        if (past_valid && reset_seen && retire_seq != $past(retire_seq)) begin
            assert($past(rst_n) && !$past(abort));
            assert(retire_seq == $past(retire_seq) + 1'b1);
            assert($past(retire_match));
            assert(done_pulse);
            assert(!result_pending);
        end
        if (past_valid && reset_seen && done_pulse) begin
            assert(retire_seq == $past(retire_seq) + 1'b1);
            assert($past(retire_match));
        end
        // Once retirement consumes a stage, another retirement requires a new stage.
        if (past_valid && reset_seen && $past(done_pulse) && !$past(abort) && rst_n)
            assert(!done_pulse);
    end
endmodule

`default_nettype wire

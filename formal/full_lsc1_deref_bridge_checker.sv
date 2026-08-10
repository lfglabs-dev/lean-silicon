`default_nettype none

// Unbounded safety checker bound inside the exact authored packet frontend.
// Reachability is intentionally checked separately: covers are bounded witnesses.
module full_lsc1_deref_bridge_checker (
    input wire clk, rst_n, abort, rx_valid, rx_ready,
    input wire tx_valid, tx_ready, input wire [7:0] tx_data,
    input wire frame_valid, event_ready, input wire [7:0] frame_opcode,
    input wire [15:0] frame_length, input wire [2047:0] frame_payload,
    input wire tx_start, input wire [3:0] compute_state,
    input wire result_pending, capture_result_crc, input wire [31:0] staged_txn_id,
    input wire [31:0] staged_next_pc, staged_next_fp, staged_result_crc,
    input wire [31:0] retire_seq, input wire done_pulse
);
    reg past_valid;
    initial past_valid = 1'b0;
    always @(posedge clk) past_valid <= 1'b1;

    wire retire_accept = frame_valid && event_ready && frame_opcode == 8'h12 &&
        frame_length == 16'd8;
    wire retire_match = retire_accept && result_pending &&
        frame_payload[0 +: 32] == staged_txn_id &&
        frame_payload[32 +: 32] == staged_result_crc;

    always @(posedge clk) begin
        if (!past_valid) assume(!rst_n);
        if (past_valid && $past(tx_valid && !tx_ready && rst_n && !abort)) begin
            assert(tx_valid);
            assert(tx_data == $past(tx_data));
        end
        if (past_valid && (!$past(rst_n) || $past(abort))) begin
            assert(!result_pending);
            assert(compute_state == 4'd0);
            assert(!tx_start);
            assert(!done_pulse);
        end
        if (past_valid && $past(result_pending) && result_pending &&
            $past(rst_n) && !$past(abort)) begin
            assert(staged_txn_id == $past(staged_txn_id));
            assert(staged_next_pc == $past(staged_next_pc));
            assert(staged_next_fp == $past(staged_next_fp));
            if (!$past(capture_result_crc))
                assert(staged_result_crc == $past(staged_result_crc));
        end
        if (past_valid && retire_seq != $past(retire_seq)) begin
            assert($past(rst_n) && !$past(abort));
            assert(retire_seq == $past(retire_seq) + 1'b1);
            assert($past(retire_match));
            assert(done_pulse);
            assert(!result_pending);
        end
        if (past_valid && done_pulse) begin
            assert(retire_seq == $past(retire_seq) + 1'b1);
            assert($past(retire_match));
        end
        // Once retirement consumes a stage, another retirement requires a new stage.
        if (past_valid && $past(done_pulse) && !$past(abort) && rst_n)
            assert(!done_pulse);
    end
endmodule

`default_nettype wire

`default_nettype none

module full_lsc1_controller_invariants (
    input wire clk, input wire rst_n, input wire abort,
    input wire rx_ready, input wire tx_valid, input wire tx_ready,
    input wire [7:0] tx_data, input wire busy, input wire fault,
    input wire done_pulse, input wire frame_valid, input wire rx_fault_valid,
    input wire tx_start, input wire tx_busy, input wire [3:0] compute_state,
    input wire alu_busy, input wire encoder_busy,
    input wire result_pending, input wire blake_result_pending,
    input wire service_pending
);
    reg past_valid = 1'b0;
    // This combinational obligation is intentionally sensitive to the production
    // instance connection, including arbitrary initial lifecycle state.
    always @(*) begin
        if (blake_result_pending) assert(result_pending);
        cover(blake_result_pending);
    end

    always @(posedge clk) begin
        past_valid <= 1'b1;
        if (!past_valid) assume(!rst_n);

        if (past_valid) begin
            // Decoder success and decoder failure are mutually exclusive events.
            assert(!(frame_valid && rx_fault_valid));
            // Every staged transaction is observable as BUSY until completion or abort.
            if (result_pending || service_pending) assert(busy);
            // A queued response is included in BUSY and cannot accept another byte.
            if (tx_start) begin assert(busy); assert(!rx_ready); end
            // Controller starts a response only at its idle arbitration boundary.
            if (tx_start) begin assert(!tx_busy); assert(compute_state == 0); end
            // Computation and every cycle of an active response exclude receive traffic.
            if (tx_busy || compute_state != 0 || alu_busy || encoder_busy) assert(!rx_ready);
        end

        if (past_valid && $past(tx_valid && !tx_ready && rst_n && !abort) && rst_n && !abort) begin
            assert(tx_valid);
            assert(tx_data == $past(tx_data));
        end
        if (past_valid && $past(!rst_n || abort)) begin
            assert(!tx_valid);
            assert(!done_pulse);
            assert(!result_pending);
            assert(!blake_result_pending);
            assert(!service_pending);
        end
        if (past_valid && done_pulse) assert(!tx_valid);
`ifndef FORMAL_BLAKE_PENDING_FOCUSED
        cover(past_valid && rst_n && tx_valid && !tx_ready);
        cover(past_valid && rst_n && fault);
        cover(past_valid && rst_n && result_pending);
        cover(past_valid && rst_n && blake_result_pending);
        cover(past_valid && rst_n && service_pending);
        cover(past_valid && rst_n && done_pulse);
`endif
    end
endmodule

`default_nettype wire

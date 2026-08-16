`default_nettype none

// Focused replacement for full_lsc1_controller_invariants in the production
// binding receipt.  The identical module interface makes the frontend's actual
// FORMAL_FULL_LSC1 instance and port expression the object of the check while
// keeping unrelated sequential controller covers out of this depth-2 job.
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
    always @(*) begin
        if (blake_result_pending) assert(result_pending);
        cover(blake_result_pending);
    end
endmodule

`default_nettype wire

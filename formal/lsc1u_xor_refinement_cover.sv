`default_nettype none

// Deterministic composed witness: accept XOR, retain a stalled result, reset
// mid-operation, then restart and retire a complete 16-lane XOR transaction.
module lsc1u_xor_refinement_cover;
    (* gclk *) reg clk;
    reg [6:0] cycle = 0;
    reg seen_accept = 0;
    reg seen_stall = 0;
    reg seen_reset_midop = 0;

    wire rst_n = (cycle != 0) && (cycle != 4);
    wire rx_valid = 1'b1;
    wire [7:0] rx_data = 8'h01;
    wire tx_ready = !(tx_valid && !seen_stall);
    wire rx_ready, tx_valid, busy, done_pulse;

    lsc1u_core dut (
        .clk(clk), .rst_n(rst_n), .ena(1'b1),
        .rx_data(rx_data), .rx_valid(rx_valid), .rx_ready(rx_ready),
        .tx_data(), .tx_valid(tx_valid), .tx_ready(tx_ready),
        .busy(busy), .fault(), .done_pulse(done_pulse)
    );

    always @(posedge clk) begin
        cycle <= cycle + 1'b1;
        if (rst_n && rx_valid && rx_ready)
            seen_accept <= 1'b1;
        if (rst_n && tx_valid && !tx_ready)
            seen_stall <= 1'b1;
        if (cycle == 4 && busy)
            seen_reset_midop <= 1'b1;
        cover(seen_accept && seen_stall && seen_reset_midop && done_pulse);
    end
endmodule

`default_nettype wire

/*
 * Diagnostic-only raw MinCore top. The product top is packetized in
 * lean_silicon_lsc1; this wrapper preserves the low-level stream-ALU harness.
 */
`default_nettype none
module lean_silicon_lsc1_mincore (
    input wire [7:0] ui_in, output wire [7:0] uo_out,
    input wire [7:0] uio_in, output wire [7:0] uio_out, output wire [7:0] uio_oe,
    input wire ena, input wire clk, input wire rst_n
);
    wire rx_ready, tx_valid, busy, fault, done_pulse;
    wire [7:0] tx_data;
    leanvm_b_stream_alu datapath_seed (
        .clk(clk), .rst_n(rst_n), .abort(uio_in[6]),
        .rx_data(ui_in), .rx_valid(uio_in[0]), .rx_ready(rx_ready),
        .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(uio_in[3]),
        .busy(busy), .done_pulse(done_pulse), .fault(fault)
    );
    assign uo_out = tx_data;
    assign uio_out = {done_pulse, 1'b0, fault, busy, 1'b0, tx_valid, rx_ready, 1'b0};
    assign uio_oe = 8'b10110110;
    wire _unused = &{ena, uio_in[7], uio_in[5], uio_in[4], uio_in[2], uio_in[1], 1'b0};
endmodule
`default_nettype wire

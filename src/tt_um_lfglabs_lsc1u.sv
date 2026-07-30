/* Tiny Tapeout pin wrapper for LSC-1u (LSC-1 Micro). */
`default_nettype none

module tt_um_lfglabs_lsc1u (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
    wire rx_ready;
    wire tx_valid;
    wire busy;
    wire fault;
    wire done_pulse;
    wire [7:0] tx_data;

    lsc1u_core core (
        .clk(clk), .rst_n(rst_n), .ena(ena),
        .rx_data(ui_in), .rx_valid(uio_in[0]),
        .rx_ready(rx_ready),
        .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(uio_in[3]),
        .busy(busy), .fault(fault), .done_pulse(done_pulse)
    );

    assign uo_out = ena ? tx_data : 8'd0;
    assign uio_out = ena ?
        {done_pulse, 1'b0, fault, busy, 1'b0, tx_valid, rx_ready, 1'b0} :
        8'd0;
    assign uio_oe = ena ? 8'b10110110 : 8'd0;

    wire _unused = &{uio_in[7:4], uio_in[2:1], 1'b0};
endmodule

`default_nettype wire

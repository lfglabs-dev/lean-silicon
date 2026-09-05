`default_nettype none
/* ULX3S v3.1.8 wrapper for the packetized LSC-1 product path. */
module ulx3s_packet_top (
    input  wire clk,
    output wire led,
    input  wire uart_rx,
    output wire uart_tx
);
    wire core_clk, pll_locked;
    ulx3s_core_pll core_pll (
        .clk_25mhz(clk), .clk_10mhz(core_clk), .locked(pll_locked)
    );

    uart_bridge #(.PACKET_MODE(1'b1), .CLK_HZ(10_000_000)) bridge (
        .clk(core_clk), .reset_hold(!pll_locked),
        .uart_rx(uart_rx), .uart_tx(uart_tx)
    );

    reg [23:0] heartbeat = 0;
    always @(posedge core_clk)
        heartbeat <= heartbeat + 1'b1;
    assign led = ~heartbeat[23];
endmodule
`default_nettype wire

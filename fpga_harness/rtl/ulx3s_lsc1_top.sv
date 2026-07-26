`default_nettype none
module ulx3s_lsc1_top (
    input  wire       clk_25mhz,
    input  wire       ftdi_txd,
    output wire       ftdi_rxd,
    output wire [7:0] led
);
    localparam integer CLKS_PER_BIT = 217; // 25 MHz / 115200 = 217.014
    reg [15:0] por_count = 16'b0;
    wire rst_n = &por_count;
    always @(posedge clk_25mhz)
        if (!rst_n)
            por_count <= por_count + 1'b1;

    wire [7:0] host_rx_data;
    wire host_rx_valid, host_rx_ready;
    wire rx_framing_error, rx_overflow;
    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) host_rx (
        .clk(clk_25mhz), .rst_n(rst_n), .serial_in(ftdi_txd),
        .data(host_rx_data), .valid(host_rx_valid), .ready(host_rx_ready),
        .framing_error(rx_framing_error), .overflow(rx_overflow)
    );

    wire [7:0] host_tx_data;
    wire host_tx_valid, host_tx_ready;
    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) host_tx (
        .clk(clk_25mhz), .rst_n(rst_n), .data(host_tx_data),
        .valid(host_tx_valid), .ready(host_tx_ready), .serial_out(ftdi_rxd)
    );

    wire [7:0] uio_in = {1'b0, 1'b0, 2'b00, host_tx_ready, 2'b00, host_rx_valid};
    wire [7:0] uio_out;
    wire [7:0] uio_oe;
    lean_silicon_lsc1 lsc1 (
        .ui_in(host_rx_data), .uo_out(host_tx_data),
        .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
        .ena(1'b1), .clk(clk_25mhz), .rst_n(rst_n)
    );
    assign host_rx_ready = uio_out[1];
    assign host_tx_valid = uio_out[2];
    assign led = {2'b00, rx_overflow, rx_framing_error,
                  !host_tx_ready, uio_out[5], uio_out[4], rst_n};
    wire _unused = &{uio_oe, uio_out[7:6], uio_out[3], uio_out[0], 1'b0};
endmodule
`default_nettype wire

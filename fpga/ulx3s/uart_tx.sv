`default_nettype none
/*
 * Conservative 1 Mbaud UART TX for 25 MHz clock.
 * 8N1, single stop bit. tx_ready indicates serializer is idle.
 */
module uart_tx #(
    parameter integer CLK_HZ = 25_000_000,
    parameter integer BAUD   = 1_000_000
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] tx_data,
    input  wire       tx_valid,
    output reg        tx_ready,
    output reg        tx_serial
);
    localparam integer DIV = CLK_HZ / BAUD;
    reg [15:0] div_cnt;
    reg [3:0]  bit_cnt;
    reg [8:0]  shift; // {stop, data[7:0]} or start+data handled inline

    always @(posedge clk) begin
        if (!rst_n) begin
            div_cnt  <= 0;
            bit_cnt  <= 0;
            tx_ready <= 1'b1;
            tx_serial <= 1'b1;
            shift    <= 9'h1FF;
        end else begin
            if (tx_ready) begin
                tx_serial <= 1'b1;
                if (tx_valid) begin
                    tx_ready <= 1'b0;
                    // Load: start bit (0) followed by 8 data bits; stop is implicit high after
                    shift   <= {tx_data, 1'b0}; // LSB first out: we shift right
                    div_cnt <= 0;
                    bit_cnt <= 0;
                end
            end else begin
                if (div_cnt == DIV-1) begin
                    div_cnt <= 0;
                    // shift out LSB
                    tx_serial <= shift[0];
                    shift <= {1'b1, shift[8:1]};
                    // bit_cnt 0 drives the start bit, 1..8 the data bits, and 9
                    // the stop bit. Releasing tx_ready at 8 would end data bit 7
                    // after a single clock instead of a full baud interval, so a
                    // receiver samples every zero-valued bit 7 as one.
                    if (bit_cnt == 9) begin
                        // The stop bit and the idle level are both high, so the
                        // ready branch holds this level until the next load.
                        tx_ready <= 1'b1;
                        bit_cnt  <= 0;
                    end else begin
                        bit_cnt <= bit_cnt + 1'b1;
                    end
                end else begin
                    div_cnt <= div_cnt + 1'b1;
                end
            end
        end
    end
endmodule
`default_nettype wire

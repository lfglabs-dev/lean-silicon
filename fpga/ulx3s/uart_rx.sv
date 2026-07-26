`default_nettype none
/*
 * Conservative 1 Mbaud UART RX for 25 MHz clock.
 * 2-flop synchronizer on rx line. 8N1, single stop bit.
 * Asserts framing_err on stop-bit failure. Drops the byte on framing error.
 * rx_valid pulses for one cycle when a clean byte is available.
 */
module uart_rx #(
    parameter integer CLK_HZ = 25_000_000,
    parameter integer BAUD   = 1_000_000
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       rx_async,
    output reg  [7:0] rx_data,
    output reg        rx_valid,
    output reg        framing_err
);
    localparam integer DIV = CLK_HZ / BAUD;
    // 2-flop synchronizer
    reg rx_m, rx_s;
    always @(posedge clk) begin
        rx_m <= rx_async;
        rx_s <= rx_m;
    end

    reg [15:0] div_cnt;
    reg [3:0]  bit_cnt;
    reg [7:0]  shift;
    reg        receiving;
    reg        wait_idle;

    always @(posedge clk) begin
        if (!rst_n) begin
            div_cnt     <= 0;
            bit_cnt     <= 0;
            shift       <= 0;
            receiving   <= 0;
            wait_idle    <= 0;
            rx_valid    <= 0;
            framing_err <= 0;
            rx_data     <= 0;
        end else begin
            rx_valid <= 0;
            framing_err <= 0;

            if (!receiving) begin
                // After a framing error (UART BREAK), require an observed high
                // level before arming another start.  Otherwise the remaining
                // low tail is mistaken for a second start and can decode as a
                // spurious 0xff byte when the line returns high.
                if (wait_idle) begin
                    if (rx_s == 1'b1)
                        wait_idle <= 1'b0;
                end else if (rx_s == 1'b0) begin
                    receiving <= 1'b1;
                    // Sample in middle of start bit: count DIV/2
                    div_cnt <= DIV[15:1];
                    bit_cnt <= 0;
                end
            end else begin
                if (div_cnt == DIV-1) begin
                    div_cnt <= 0;
                    if (bit_cnt == 0) begin
                        // Verify start bit still low at sample point
                        if (rx_s != 1'b0) begin
                            receiving <= 0;
                        end else begin
                            bit_cnt <= bit_cnt + 1'b1;
                        end
                    end else if (bit_cnt <= 8) begin
                        shift[bit_cnt-1] <= rx_s;
                        bit_cnt <= bit_cnt + 1'b1;
                    end else begin
                        // Stop bit
                        if (rx_s != 1'b1) begin
                            framing_err <= 1'b1;
                            wait_idle <= 1'b1;
                        end else begin
                            rx_data  <= shift;
                            rx_valid <= 1'b1;
                        end
                        receiving <= 0;
                    end
                end else begin
                    div_cnt <= div_cnt + 1'b1;
                end
            end
        end
    end
endmodule
`default_nettype wire

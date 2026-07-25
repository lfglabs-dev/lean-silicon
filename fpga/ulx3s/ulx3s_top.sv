`default_nettype none
/*
 * ULX3S v3.1.8 top: selects between smoke and UART bridge via parameter.
 * Default: UART bridge (P1 deliverable). Smoke is a separate minimal target.
 *
 * This file is the board-level wrapper. It does NOT widen the ASIC boundary.
 */
module ulx3s_top #(
    parameter bit USE_SMOKE = 1'b0
) (
    input  wire clk,      // G2 25 MHz
    output wire led,      // B2 LED0 (active low)
    input  wire uart_rx,  // M1 from FT231X
    output wire uart_tx   // L4 to FT231X
);

    generate
        if (USE_SMOKE) begin : g_smoke
            smoke_top u_smoke (
                .clk(clk),
                .led(led)
            );
            assign uart_tx = 1'b1; // idle
            wire _u = uart_rx;
        end else begin : g_uart
            uart_bridge u_bridge (
                .clk(clk),
                .uart_rx(uart_rx),
                .uart_tx(uart_tx)
            );
            // Optional heartbeat on LED: toggle slowly when bridge idle
            reg [23:0] hb;
            always @(posedge clk) hb <= hb + 1'b1;
            assign led = ~hb[23]; // gentle heartbeat; real activity is UART
        end
    endgenerate
endmodule
`default_nettype wire

`default_nettype none
/*
 * Minimal 25 MHz counter/LED smoke for ULX3S v3.1.8 / LFE5U-85F.
 * Purpose: prove reproducible yosys -> nextpnr-ecp5 -> ecppack flow.
 * No ASIC core instantiated. No UART. Pure fabric heartbeat.
 */
module smoke_top (
    input  wire clk,
    output wire led
);
    // 25 MHz clock domain. 25-bit counter for visible blink (~0.67 s period).
    reg [24:0] cnt;
    always @(posedge clk) begin
        cnt <= cnt + 1'b1;
    end
    // Active-low LED on ULX3S: drive low to light.
    assign led = ~cnt[24];
endmodule
`default_nettype wire

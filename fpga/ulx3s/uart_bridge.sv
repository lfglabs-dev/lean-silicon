`default_nettype none
/*
 * UART <-> LSC-1 pin bridge for ULX3S SRAM smoke.
 * - Instantiates exact lean_silicon_lsc1 (no wide bypass).
 * - 2-flop sync UART RX at 1 Mbaud (25 MHz / 25).
 * - UART TX at 1 Mbaud.
 * - Byte buffering + backpressure: only assert RX_VALID when core rx_ready.
 * - POR reset synchroniser (2-flop).
 * - External ABORT from a framing error or host command byte 0x7f treated as abort pulse.
 *
 * Pin contract preserved: every byte crosses ui_in / uo_out / uio_* exactly.
 */
module uart_bridge (
    input  wire clk,       // 25 MHz
    input  wire uart_rx,   // async from FTDI (M1)
    output wire uart_tx    // to FTDI (L4)
);
    // POR reset synchroniser (active-low)
    reg rst_m, rst_n;
    always @(posedge clk) begin
        rst_m <= 1'b1;     // async deassert captured
        rst_n <= rst_m;
    end

    // UART RX
    wire [7:0] uart_rx_data;
    wire       uart_rx_valid;
    wire       uart_framing_err;

    uart_rx #(
        .CLK_HZ(25_000_000),
        .BAUD(1_000_000)
    ) urx (
        .clk(clk),
        .rst_n(rst_n),
        .rx_async(uart_rx),
        .rx_data(uart_rx_data),
        .rx_valid(uart_rx_valid),
        .framing_err(uart_framing_err)
    );

    // UART TX
    wire [7:0] uart_tx_data;
    wire       uart_tx_valid;
    wire       uart_tx_ready;

    uart_tx #(
        .CLK_HZ(25_000_000),
        .BAUD(1_000_000)
    ) utx (
        .clk(clk),
        .rst_n(rst_n),
        .tx_data(uart_tx_data),
        .tx_valid(uart_tx_valid),
        .tx_ready(uart_tx_ready),
        .tx_serial(uart_tx)
    );

    // Exact ASIC pin interface (ui/uio) - NO wide ports exposed
    wire [7:0] ui_in;
    wire [7:0] uo_out;
    wire [7:0] uio_in;
    wire [7:0] uio_out;
    wire [7:0] uio_oe;

    // Bridge control:
    // Host drives: uio_in[0]=RX_VALID, uio_in[3]=TX_READY, uio_in[6]=ABORT
    // ASIC drives: uio_out[1]=RX_READY, uio_out[2]=TX_VALID, ...
    // We sample uio_out (ASIC outputs) and drive uio_in (host inputs).
    // Simple policy:
    // - Forward uart_rx_data to ui_in when we have a byte and core is ready.
    // - Assert RX_VALID only for one cycle when a clean byte is accepted.
    // - When core asserts TX_VALID and we have TX_READY, forward uo_out to uart.
    // - Backpressure: if uart_tx not ready, hold TX_READY low to core.

    reg        rx_valid_q;
    reg [7:0]  rx_data_q;
    reg        tx_ready_q;
    reg        abort_q;
    reg        frame_abort;

    // One-cycle framing abort pulse
    always @(posedge clk) begin
        if (!rst_n) frame_abort <= 1'b0;
        else frame_abort <= uart_framing_err;
    end

    // Host->core forwarding with backpressure
    always @(posedge clk) begin
        if (!rst_n) begin
            rx_valid_q <= 1'b0;
            rx_data_q  <= 8'h00;
            abort_q    <= 1'b0;
        end else begin
            // Default: deassert after one cycle unless re-armed
            rx_valid_q <= 1'b0;
            abort_q    <= frame_abort;

            if (uart_rx_valid && !uart_framing_err) begin
                // Accept a byte from UART only if core can take it this cycle.
                // If not, we drop it (harness policy: host must not overrun without flow control).
                // A production harness would NACK or buffer; here we keep it minimal.
                if (uio_out[1]) begin // RX_READY from core
                    rx_valid_q <= 1'b1;
                    rx_data_q  <= uart_rx_data;
                end
            end

            // Host can send 0x7f as explicit abort
            if (uart_rx_valid && uart_rx_data == 8'h7f && !uart_framing_err) begin
                abort_q <= 1'b1;
            end
        end
    end

    // Core->host forwarding
    always @(posedge clk) begin
        if (!rst_n) begin
            tx_ready_q <= 1'b0;
        end else begin
            // Only offer TX_READY when the UART serializer is idle
            tx_ready_q <= uart_tx_ready;
        end
    end

    // Wire the exact 8-bit interface
    assign ui_in  = rx_data_q;
    assign uio_in = {1'b0, abort_q, 1'b0, 1'b0, tx_ready_q, 1'b0, 1'b0, rx_valid_q};

    // Core produces uo_out (tx_data) when uio_out[2] (TX_VALID) is high.
    // We register a one-cycle pulse to the UART when we see TX_VALID && TX_READY.
    reg        core_tx_fire;
    reg [7:0]  core_tx_data;
    always @(posedge clk) begin
        if (!rst_n) begin
            core_tx_fire <= 1'b0;
            core_tx_data <= 8'h00;
        end else begin
            core_tx_fire <= uio_out[2] && tx_ready_q;
            if (uio_out[2] && tx_ready_q) begin
                core_tx_data <= uo_out;
            end
        end
    end

    assign uart_tx_data  = core_tx_data;
    assign uart_tx_valid = core_tx_fire;

    // Instantiate the exact contract top (MinCore seed, not v1 packet)
    lean_silicon_lsc1 asic (
        .ui_in  (ui_in),
        .uo_out (uo_out),
        .uio_in (uio_in),
        .uio_out(uio_out),
        .uio_oe (uio_oe),
        .ena    (1'b1),
        .clk    (clk),
        .rst_n  (rst_n)
    );

    // Unused uio_oe and other bits are left floating in harness; ASIC drives them.
    wire _unused = &{uio_oe, 1'b0};

endmodule
`default_nettype wire

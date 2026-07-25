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
    // Power-on reset (active-low). The shift register starts at zero, so rst_n
    // is genuinely held low for POR_CYCLES edges before it releases. A
    // synchroniser that only ever shifts in ones never asserts reset at all,
    // which leaves every register in this file and in the core undefined.
    localparam integer POR_CYCLES = 8;
    reg [POR_CYCLES-1:0] por_shift = {POR_CYCLES{1'b0}};
    always @(posedge clk) por_shift <= {por_shift[POR_CYCLES-2:0], 1'b1};
    wire rst_n = por_shift[POR_CYCLES-1];

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
    //
    // Both directions use a one-deep buffer whose ready deasserts on the very
    // handshake that fills it. That is what makes the ready/valid contract hold
    // in both directions: a byte is never presented to a side that has not
    // signalled room for it, and never replaced before the far side took it.

    reg       abort_q;

    // Framing errors and the explicit 0x7f abort byte both produce a one-cycle
    // abort pulse. uart_framing_err and uart_rx_valid are themselves one-cycle
    // pulses, so no extra edge detection is needed.
    wire rx_byte_ok  = uart_rx_valid && !uart_framing_err;
    wire rx_is_abort = rx_byte_ok && (uart_rx_data == 8'h7f);

    always @(posedge clk) begin
        if (!rst_n) abort_q <= 1'b0;
        else        abort_q <= uart_framing_err || rx_is_abort;
    end

    // ---- host -> core ----------------------------------------------------
    // RX_VALID stays asserted until the core completes the handshake. Sampling
    // RX_READY a cycle early and pulsing RX_VALID regardless discards every
    // byte that arrives while the core is mid-transaction.
    reg       rx_full;
    reg [7:0] rx_data_q;
    reg       rx_overrun;

    wire core_rx_ready = uio_out[1];
    wire rx_core_fire  = rx_full && core_rx_ready;
    wire rx_accept     = rx_byte_ok && !rx_is_abort;

    always @(posedge clk) begin
        if (!rst_n) begin
            rx_full   <= 1'b0;
            rx_data_q <= 8'h00;
        end else if (abort_q) begin
            // The buffered byte belongs to the transaction being abandoned.
            rx_full   <= 1'b0;
        end else if (rx_accept) begin
            rx_data_q <= uart_rx_data;
            rx_full   <= 1'b1;
        end else if (rx_core_fire) begin
            rx_full   <= 1'b0;
        end
    end

    // Sticky observability probe: a byte arrived while the buffer was still
    // full and not being drained, so it displaced one the core never read.
    // Testbenches assert this stays clear; it drives no logic.
    always @(posedge clk) begin
        if (!rst_n) rx_overrun <= 1'b0;
        else if (rx_accept && rx_full && !rx_core_fire) rx_overrun <= 1'b1;
    end

    // ---- core -> host ----------------------------------------------------
    // TX_READY is the buffer-empty flag, so it drops on the same edge the core
    // hands a byte over. Mirroring the serialiser's ready one cycle late lets
    // the core complete a second handshake while the serialiser is already
    // busy, and that byte is overwritten instead of sent.
    reg       tx_full;
    reg [7:0] tx_data_q;

    wire core_tx_valid = uio_out[2];
    wire core_tx_ready = !tx_full;
    wire tx_core_fire  = core_tx_valid && core_tx_ready;
    wire tx_uart_fire  = tx_full && uart_tx_ready;

    always @(posedge clk) begin
        if (!rst_n) begin
            tx_full   <= 1'b0;
            tx_data_q <= 8'h00;
        end else if (abort_q) begin
            tx_full   <= 1'b0;
        end else if (tx_core_fire) begin
            tx_data_q <= uo_out;
            tx_full   <= 1'b1;
        end else if (tx_uart_fire) begin
            tx_full   <= 1'b0;
        end
    end

    // Wire the exact 8-bit interface
    assign ui_in  = rx_data_q;
    assign uio_in = {1'b0, abort_q, 1'b0, 1'b0, core_tx_ready, 1'b0, 1'b0, rx_full};

    assign uart_tx_data  = tx_data_q;
    assign uart_tx_valid = tx_full;

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
    wire _unused = &{uio_oe, rx_overrun, 1'b0};

endmodule
`default_nettype wire

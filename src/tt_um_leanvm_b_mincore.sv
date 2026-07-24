/*
 * Tiny Tapeout wrapper for the leanVM-b MinCore streaming opcode engine.
 * SPDX-License-Identifier: Apache-2.0
 */
`default_nettype none

module tt_um_leanvm_b_mincore (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    wire       rx_valid = uio_in[0];
    wire       tx_ready = uio_in[3];
    wire       abort    = uio_in[6];
    wire       rx_ready;
    wire [7:0] tx_data;
    wire       tx_valid;
    wire       busy;
    wire       done_pulse;
    wire       fault;

    leanvm_b_stream_alu core (
        .clk        (clk),
        .rst_n      (rst_n),
        .abort      (abort),
        .rx_data    (ui_in),
        .rx_valid   (rx_valid),
        .rx_ready   (rx_ready),
        .tx_data    (tx_data),
        .tx_valid   (tx_valid),
        .tx_ready   (tx_ready),
        .busy       (busy),
        .done_pulse (done_pulse),
        .fault      (fault)
    );

    assign uo_out = tx_data;

    // Fixed directions:
    //   uio[0] host->chip RX_VALID      (input)
    //   uio[1] chip->host RX_READY      (output)
    //   uio[2] chip->host TX_VALID      (output)
    //   uio[3] host->chip TX_READY      (input)
    //   uio[4] chip->host BUSY          (output)
    //   uio[5] chip->host FAULT         (output)
    //   uio[6] host->chip ABORT         (input)
    //   uio[7] chip->host DONE_PULSE    (output)
    assign uio_out = {
        done_pulse,
        1'b0,
        fault,
        busy,
        1'b0,
        tx_valid,
        rx_ready,
        1'b0
    };

    assign uio_oe = 8'b10110110;

    wire _unused = &{ena, uio_in[7], uio_in[5], uio_in[4], uio_in[2], uio_in[1], 1'b0};

endmodule

`default_nettype wire

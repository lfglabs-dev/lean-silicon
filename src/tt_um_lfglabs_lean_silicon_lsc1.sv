/*
 * Tiny Tapeout integration wrapper for the canonical LSC-1 ASIC boundary.
 * SPDX-License-Identifier: Apache-2.0
 */
`default_nettype none

module tt_um_lfglabs_lean_silicon_lsc1 (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
    wire [7:0] core_uo_out;
    wire [7:0] core_uio_out;
    wire [7:0] core_uio_oe;

    // Do not present handshakes or ABORT to the core while this TT project is
    // deselected. Reserved input positions remain explicit and deterministic.
    wire [7:0] core_uio_in = {
        1'b0,                 // [7] output at the core boundary
        uio_in[6] & ena,      // [6] ABORT
        1'b0,                 // [5] output at the core boundary
        1'b0,                 // [4] output at the core boundary
        uio_in[3] & ena,      // [3] RESPONSE_READY
        1'b0,                 // [2] output at the core boundary
        1'b0,                 // [1] output at the core boundary
        uio_in[0] & ena       // [0] REQUEST_VALID
    };

    lean_silicon_lsc1 core (
        .ui_in   (ui_in),
        .uo_out  (core_uo_out),
        .uio_in  (core_uio_in),
        .uio_out (core_uio_out),
        .uio_oe  (core_uio_oe),
        .ena     (ena),
        .clk     (clk),
        .rst_n   (rst_n)
    );

    // A deselected project never drives the shared bidirectional pins and
    // presents zero on dedicated outputs. Every output is assigned.
    assign uo_out  = ena ? core_uo_out  : 8'b0;
    assign uio_out = ena ? core_uio_out : 8'b0;
    assign uio_oe  = ena ? core_uio_oe  : 8'b0;

    // Input-only uio positions are intentionally ignored on the output side.
    wire _unused = &{uio_in[7], uio_in[5], uio_in[4],
                     uio_in[2], uio_in[1], 1'b0};
endmodule

`default_nettype wire

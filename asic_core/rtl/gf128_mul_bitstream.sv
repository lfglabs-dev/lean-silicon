/*
 * leanVM-b specialization of gf2n_mul_bitstream.
 *
 * GF(2^128) = GF(2)[x] / (x^128 + x^7 + x^2 + x + 1), so the
 * low reduction constant is 0x87. Bytes and multiplier bits are little-endian.
 */
`default_nettype none

module gf128_mul_bitstream (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         abort,

    input  wire         a_valid,
    input  wire [7:0]   a_byte,
    input  wire         a_last,

    input  wire         bit_valid,
    input  wire         bit_value,
    input  wire         bit_last,

    input  wire         result_shift,
    output wire [7:0]   result_byte,
    output wire [127:0] arch_a_shift,
    output wire [127:0] arch_accumulator
);

    gf2n_mul_bitstream #(
        .WIDTH        (128),
        .BYTE_BITS    (8),
        .MODULUS_LOW  (128'h00000000000000000000000000000087)
    ) impl (
        .clk          (clk),
        .rst_n        (rst_n),
        .abort        (abort),
        .a_valid      (a_valid),
        .a_byte       (a_byte),
        .a_last       (a_last),
        .bit_valid    (bit_valid),
        .bit_value    (bit_value),
        .bit_last     (bit_last),
        .result_shift (result_shift),
        .result_byte  (result_byte),
        .arch_a_shift (arch_a_shift),
        .arch_accumulator (arch_accumulator)
    );

endmodule

`default_nettype wire

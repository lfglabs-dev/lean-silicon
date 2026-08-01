/*
 * Conservative formal boundary for lsc1u_core protocol proofs.
 *
 * The concrete GF(2^128) implementation is proved separately by
 * gf128_serialize.sby and the exhaustive generic-arithmetic check in
 * gf8_mul.sby.  None of the LSC-1u control/framing assertions depends on the
 * multiplier result value, so leaving it unconstrained removes irrelevant
 * 256-bit datapath state while considering strictly more output behaviours.
 */
`default_nettype none

module gf128_mul_bitstream (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       abort,
    input  wire       a_valid,
    input  wire [7:0] a_byte,
    input  wire       a_last,
    input  wire       bit_valid,
    input  wire       bit_value,
    input  wire       bit_last,
    input  wire       result_shift,
    output wire [7:0] result_byte
`ifdef FORMAL
    , output wire [127:0] formal_a_shift
    , output wire [127:0] formal_accumulator
`endif
);
    (* anyseq *) wire [7:0] unconstrained_result;
    assign result_byte = unconstrained_result;
`ifdef FORMAL
    assign formal_a_shift = 128'd0;
    assign formal_accumulator = {120'd0, unconstrained_result};
`endif
endmodule

`default_nettype wire

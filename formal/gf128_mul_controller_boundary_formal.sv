`default_nettype none

// Conservative controller-proof boundary for gf128_mul_bitstream. Arithmetic
// and accepted-event behavior are proved by gf128_mul_stream_refinement.sby.
module gf128_mul_bitstream (
    input wire clk, rst_n, abort,
    input wire a_valid, a_last,
    input wire [7:0] a_byte,
    input wire bit_valid, bit_value, bit_last, result_shift,
    output wire [7:0] result_byte
`ifdef FORMAL
    , output wire [127:0] formal_a_shift
    , output wire [127:0] formal_accumulator
`endif
);
    (* anyseq *) wire [7:0] arbitrary_result_byte;

    assign result_byte = arbitrary_result_byte;
`ifdef FORMAL
    // The low byte keeps the controller's multiplier-output mux observable
    // without importing the executable multiplier's 384 state bits into PDR.
    assign formal_a_shift = 128'd0;
    assign formal_accumulator = {120'd0, arbitrary_result_byte};
`endif
endmodule

`default_nettype wire

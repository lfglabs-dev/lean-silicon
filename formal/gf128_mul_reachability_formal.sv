`default_nettype none

// A concrete multiplier-result witness is sufficient for control reachability:
// lsc1u_core never branches on result_byte.
module gf128_mul_bitstream (
    input wire clk, rst_n, abort, a_valid, a_last,
    input wire [7:0] a_byte,
    input wire bit_valid, bit_value, bit_last, result_shift,
    output wire [7:0] result_byte
);
    assign result_byte = 8'h00;
endmodule

`default_nettype wire

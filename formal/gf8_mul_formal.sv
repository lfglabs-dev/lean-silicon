/*
 * SymbiYosys harness for the WIDTH=8 specialization of gf2n_mul_bitstream.
 * The final assertion compares the serial RTL against an independent
 * carry-less schoolbook product plus polynomial long reduction.
 */
`default_nettype none

module gf8_mul_formal;
    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg [4:0] phase = 5'd0;

    (* anyconst *) wire [7:0] operand_a;
    (* anyconst *) wire [7:0] operand_b;

    always @($global_clock)
        clk <= ~clk;

    wire a_valid = (phase == 5'd1);
    wire bit_valid = (phase >= 5'd2) && (phase <= 5'd9);
    wire bit_last = (phase == 5'd9);
    wire bit_value = operand_b[phase - 5'd2];
    wire [7:0] result_byte;

    gf2n_mul_bitstream #(
        .WIDTH       (8),
        .BYTE_BITS   (8),
        .MODULUS_LOW (8'h1b)
    ) dut (
        .clk          (clk),
        .rst_n        (rst_n),
        .abort        (1'b0),
        .a_valid      (a_valid),
        .a_byte       (operand_a),
        .a_last       (1'b1),
        .bit_valid    (bit_valid),
        .bit_value    (bit_value),
        .bit_last     (bit_last),
        .result_shift (1'b0),
        .result_byte  (result_byte)
    );

    function automatic [7:0] reference_mul;
        input [7:0] a;
        input [7:0] b;
        reg [7:0] x;
        begin
            // This is a separate, fully unrolled polynomial-basis oracle:
            // a*x^i is reduced before being conditionally accumulated.
            // It is algebraically equivalent to schoolbook multiplication
            // followed by reduction modulo x^8 + x^4 + x^3 + x + 1.
            reference_mul = 8'b0;
            x = a;
            if (b[0]) reference_mul = reference_mul ^ x;
            x = {x[6:0], 1'b0} ^ (x[7] ? 8'h1b : 8'b0);
            if (b[1]) reference_mul = reference_mul ^ x;
            x = {x[6:0], 1'b0} ^ (x[7] ? 8'h1b : 8'b0);
            if (b[2]) reference_mul = reference_mul ^ x;
            x = {x[6:0], 1'b0} ^ (x[7] ? 8'h1b : 8'b0);
            if (b[3]) reference_mul = reference_mul ^ x;
            x = {x[6:0], 1'b0} ^ (x[7] ? 8'h1b : 8'b0);
            if (b[4]) reference_mul = reference_mul ^ x;
            x = {x[6:0], 1'b0} ^ (x[7] ? 8'h1b : 8'b0);
            if (b[5]) reference_mul = reference_mul ^ x;
            x = {x[6:0], 1'b0} ^ (x[7] ? 8'h1b : 8'b0);
            if (b[6]) reference_mul = reference_mul ^ x;
            x = {x[6:0], 1'b0} ^ (x[7] ? 8'h1b : 8'b0);
            if (b[7]) reference_mul = reference_mul ^ x;
        end
    endfunction

    always @(posedge clk) begin
        if (phase == 5'd0) begin
            rst_n <= 1'b1;
            phase <= 5'd1;
        end else if (phase < 5'd11) begin
            phase <= phase + 1'b1;
        end

        if (phase == 5'd10) begin
            // This assertion is reached after eight multiplier-bit handshakes.
            assert(result_byte == reference_mul(operand_a, operand_b));
            cover(1'b1);
        end
    end

endmodule

`default_nettype wire

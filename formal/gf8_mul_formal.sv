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
        reg [14:0] product;
        integer i;
        begin
            product = 15'b0;
            for (i = 0; i < 8; i = i + 1)
                if (b[i])
                    product = product ^ ({7'b0, a} << i);

            for (i = 14; i >= 8; i = i - 1)
                if (product[i])
                    product = product ^ (15'h11b << (i - 8));

            reference_mul = product[7:0];
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

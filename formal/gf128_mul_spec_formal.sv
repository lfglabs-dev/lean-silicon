`default_nettype none

// Executable contract used only at the controller-composition boundary.
// It implements the mathematical Horner/shift-and-add specification over
// accepted events, independently of the production multiplier's structure.
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
    reg [127:0] operand;
    reg [127:0] power;
    reg [127:0] product;

    function automatic [127:0] xtime;
        input [127:0] value;
        begin
            xtime = {value[126:0], 1'b0} ^
                    (value[127] ? 128'h87 : 128'h0);
        end
    endfunction

    assign result_byte = product[7:0];
`ifdef FORMAL
    assign formal_a_shift = power;
    assign formal_accumulator = product;
`endif

    always @(posedge clk) begin
        if (!rst_n || abort) begin
            operand <= 128'd0;
            power   <= 128'd0;
            product <= 128'd0;
        end else if (a_valid) begin
            operand <= {a_byte, operand[127:8]};
            if (a_last) begin
                power   <= {a_byte, operand[127:8]};
                product <= 128'd0;
            end
        end else if (bit_valid) begin
            if (bit_value)
                product <= product ^ power;
            if (!bit_last)
                power <= xtime(power);
        end else if (result_shift) begin
            product <= product >> 8;
        end
    end
endmodule

`default_nettype wire

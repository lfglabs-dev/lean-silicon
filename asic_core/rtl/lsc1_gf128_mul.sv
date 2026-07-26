`default_nettype none

// One reusable, fixed-latency GF(2^128) multiplier for the packet controller.
// Coefficients and bytes are little-endian; reduction is by
// x^128 + x^7 + x^2 + x + 1.
module lsc1_gf128_mul (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         abort,
    input  wire         start,
    input  wire [127:0] operand_a,
    input  wire [127:0] operand_b,
    output wire         busy,
    output reg          done_pulse,
    output reg  [127:0] result
);
    reg active;
    reg [7:0] bit_count;
    reg [127:0] multiplicand;
    reg [127:0] multiplier;
    reg [127:0] accumulator;
    wire [127:0] accumulated =
        multiplier[0] ? (accumulator ^ multiplicand) : accumulator;

    assign busy = active;

    always @(posedge clk) begin
        if (!rst_n || abort) begin
            active <= 1'b0;
            bit_count <= 0;
            multiplicand <= 0;
            multiplier <= 0;
            accumulator <= 0;
            result <= 0;
            done_pulse <= 1'b0;
        end else begin
            done_pulse <= 1'b0;
            if (start && !active) begin
                active <= 1'b1;
                bit_count <= 0;
                multiplicand <= operand_a;
                multiplier <= operand_b;
                accumulator <= 0;
            end else if (active) begin
                if (bit_count == 8'd127) begin
                    result <= accumulated;
                    active <= 1'b0;
                    done_pulse <= 1'b1;
                end else begin
                    accumulator <= accumulated;
                    multiplicand <= multiplicand[127] ?
                        ((multiplicand << 1) ^ 128'h87) :
                        (multiplicand << 1);
                    multiplier <= multiplier >> 1;
                    bit_count <= bit_count + 1'b1;
                end
            end
        end
    end
endmodule

`default_nettype wire

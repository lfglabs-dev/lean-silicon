/*
 * Generic sequential-load, bit-stepped GF(2^N) multiplier datapath.
 *
 * Area choices:
 *   - A bytes are shifted directly into the sole multiplicand register;
 *     no indexed-write decoder or duplicate A register is required.
 *   - multiplier bits are supplied by the parent FSM, so no B register or
 *     internal cycle counter is required.
 *   - the result is destructively serialized from accumulator[BYTE_BITS-1:0],
 *     avoiding a WIDTH/BYTE_BITS-way output mux.
 *
 * Polynomial basis convention:
 *   - bit i is the coefficient of x^i;
 *   - MODULUS_LOW contains the lower N coefficients of the monic modulus;
 *   - A bytes and multiplier bits arrive least-significant first.
 *
 * The parent must issue mutually exclusive a_valid, bit_valid, and
 * result_shift pulses.  `bit_last` suppresses the final unnecessary xtime.
 */
`default_nettype none

module gf2n_mul_bitstream #(
    parameter integer WIDTH = 128,
    parameter integer BYTE_BITS = 8,
    parameter [WIDTH-1:0] MODULUS_LOW = 8'h87
) (
    input  wire                    clk,
    input  wire                    rst_n,
    input  wire                    abort,

    input  wire                    a_valid,
    input  wire [BYTE_BITS-1:0]    a_byte,
    input  wire                    a_last,

    input  wire                    bit_valid,
    input  wire                    bit_value,
    input  wire                    bit_last,

    input  wire                    result_shift,
    output wire [BYTE_BITS-1:0]    result_byte,
    output wire [WIDTH-1:0]        arch_a_shift,
    output wire [WIDTH-1:0]        arch_accumulator
);

    reg [WIDTH-1:0] a_shift;
    reg [WIDTH-1:0] accumulator;

    wire [WIDTH-1:0] selected = bit_value ? a_shift : {WIDTH{1'b0}};
    wire [WIDTH-1:0] accumulator_next = accumulator ^ selected;

    function automatic [WIDTH-1:0] shift_in_byte;
        input [WIDTH-1:0] value;
        input [BYTE_BITS-1:0] byte_value;
        reg [WIDTH-1:0] next_value;
        begin
            next_value = value >> BYTE_BITS;
            next_value[WIDTH-1 -: BYTE_BITS] = byte_value;
            shift_in_byte = next_value;
        end
    endfunction

    function automatic [WIDTH-1:0] mul_by_x;
        input [WIDTH-1:0] value;
        reg carry;
        begin
            carry = value[WIDTH-1];
            mul_by_x = {value[WIDTH-2:0], 1'b0} ^
                       (carry ? MODULUS_LOW : {WIDTH{1'b0}});
        end
    endfunction

    assign result_byte = accumulator[BYTE_BITS-1:0];
    assign arch_a_shift = a_shift;
    assign arch_accumulator = accumulator;

    always @(posedge clk) begin
        if (!rst_n) begin
            a_shift     <= {WIDTH{1'b0}};
            accumulator <= {WIDTH{1'b0}};
        end else if (abort) begin
            a_shift     <= {WIDTH{1'b0}};
            accumulator <= {WIDTH{1'b0}};
        end else if (a_valid) begin
            a_shift <= shift_in_byte(a_shift, a_byte);
            if (a_last)
                accumulator <= {WIDTH{1'b0}};
        end else if (bit_valid) begin
            accumulator <= accumulator_next;
            if (!bit_last)
                a_shift <= mul_by_x(a_shift);
        end else if (result_shift) begin
            accumulator <= accumulator >> BYTE_BITS;
        end
    end

endmodule

`default_nettype wire

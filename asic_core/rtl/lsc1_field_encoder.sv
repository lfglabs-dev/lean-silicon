`default_nettype none

// Sequential g^index encoder for the 16-bit LSC-1 pointer window.  Reuses the
// byte-stream multiplier so pointer witnesses are checked by the same physical
// arithmetic datapath as MUL_NATIVE.
module lsc1_field_encoder (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         abort,
    input  wire         start,
    input  wire [15:0]  index,
    output reg          busy,
    output reg          done_pulse,
    output reg          fault,
    output reg  [127:0] result,
    output wire [4:0]   arch_bit_index,
    output wire [15:0]  arch_saved_index
);
    reg         multiply_start;
    reg [4:0]   bit_index;
    reg [15:0]  saved_index;
    reg [127:0] accumulator;
    reg [127:0] operand_a, operand_b;
    wire        multiply_busy, multiply_done, multiply_fault;
    wire [127:0] multiply_result;
    reg [127:0] next_accumulator;
    assign arch_bit_index = bit_index;
    assign arch_saved_index = saved_index;

    function automatic [127:0] field_xtime(input [127:0] value);
        field_xtime = {value[126:0], 1'b0} ^
                      (value[127] ? 128'h87 : 128'h0);
    endfunction

    lsc1_stream_adapter multiplier (
        .clk(clk), .rst_n(rst_n), .abort(abort), .start(multiply_start),
        .operation(8'h02), .operand_a(operand_a), .operand_b(operand_b),
        .busy(multiply_busy), .done_pulse(multiply_done),
        .fault(multiply_fault), .result(multiply_result)
    );

    always @(posedge clk) begin
        if (!rst_n || abort) begin
            busy <= 1'b0;
            done_pulse <= 1'b0;
            fault <= 1'b0;
            result <= 0;
            multiply_start <= 1'b0;
            bit_index <= 0;
            saved_index <= 0;
            accumulator <= 0;
            operand_a <= 0;
            operand_b <= 0;
        end else begin
            multiply_start <= 1'b0;
            done_pulse <= 1'b0;
            if (start && !busy) begin
                busy <= 1'b1;
                fault <= 1'b0;
                saved_index <= index;
                bit_index <= 15;
                accumulator <= 128'h1;
                operand_a <= 128'h1;
                operand_b <= 128'h1;
                multiply_start <= 1'b1;
            end else if (busy && multiply_done) begin
                next_accumulator = saved_index[bit_index]
                    ? field_xtime(multiply_result) : multiply_result;
                if (multiply_fault) begin
                    busy <= 1'b0;
                    fault <= 1'b1;
                    done_pulse <= 1'b1;
                end else if (bit_index == 0) begin
                    accumulator <= next_accumulator;
                    result <= next_accumulator;
                    busy <= 1'b0;
                    done_pulse <= 1'b1;
                end else begin
                    accumulator <= next_accumulator;
                    bit_index <= bit_index - 1'b1;
                    operand_a <= next_accumulator;
                    operand_b <= next_accumulator;
                    multiply_start <= 1'b1;
                end
            end
        end
    end

    wire _unused_multiplier_busy = multiply_busy;
endmodule

`default_nettype wire

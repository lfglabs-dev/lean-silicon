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
    output wire [15:0]  arch_saved_index,
    output wire         arch_multiply_start,
    output wire [127:0] arch_accumulator,
    output wire [127:0] arch_operand_a,
    output wire [127:0] arch_operand_b,
    output wire         arch_done_pulse,
    output wire         arch_fault,
    output wire [127:0] arch_result,
    output wire [2:0]   arch_multiplier_state,
    output wire [7:0]   arch_multiplier_operation,
    output wire [5:0]   arch_multiplier_payload_index,
    output wire [4:0]   arch_multiplier_result_index,
    output wire [127:0] arch_multiplier_saved_a,
    output wire [127:0] arch_multiplier_saved_b,
    output wire         arch_multiplier_done_pulse,
    output wire         arch_multiplier_fault,
    output wire [127:0] arch_multiplier_result,
    output wire [3:0]   arch_multiplier_core_state,
    output wire [3:0]   arch_multiplier_core_byte_index,
    output wire [7:0]   arch_multiplier_core_scratch_byte,
    output wire         arch_multiplier_core_fault,
    output wire [127:0] arch_multiplier_core_mul_a_shift,
    output wire [127:0] arch_multiplier_core_mul_accumulator
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
    assign arch_multiply_start = multiply_start;
    assign arch_accumulator = accumulator;
    assign arch_operand_a = operand_a;
    assign arch_operand_b = operand_b;
    assign arch_done_pulse = done_pulse;
    assign arch_fault = fault;
    assign arch_result = result;

    function automatic [127:0] field_xtime(input [127:0] value);
        field_xtime = {value[126:0], 1'b0} ^
                      (value[127] ? 128'h87 : 128'h0);
    endfunction

    lsc1_stream_adapter multiplier (
        .clk(clk), .rst_n(rst_n), .abort(abort), .start(multiply_start),
        .operation(8'h02), .operand_a(operand_a), .operand_b(operand_b),
        .busy(multiply_busy), .done_pulse(multiply_done),
        .fault(multiply_fault), .result(multiply_result),
        .arch_state(arch_multiplier_state), .arch_operation(arch_multiplier_operation),
        .arch_payload_index(arch_multiplier_payload_index), .arch_result_index(arch_multiplier_result_index),
        .arch_saved_a(arch_multiplier_saved_a), .arch_saved_b(arch_multiplier_saved_b),
        .arch_done_pulse(arch_multiplier_done_pulse), .arch_fault(arch_multiplier_fault),
        .arch_result(arch_multiplier_result),
        .arch_core_state(arch_multiplier_core_state), .arch_core_byte_index(arch_multiplier_core_byte_index),
        .arch_core_scratch_byte(arch_multiplier_core_scratch_byte), .arch_core_fault(arch_multiplier_core_fault),
        .arch_core_mul_a_shift(arch_multiplier_core_mul_a_shift),
        .arch_core_mul_accumulator(arch_multiplier_core_mul_accumulator)
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

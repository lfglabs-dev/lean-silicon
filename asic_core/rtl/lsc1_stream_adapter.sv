`default_nettype none

// Converts one validated packet operation into the byte-level MinCore stream
// consumed by the shipped leanvm_b_stream_alu.  This is the explicit boundary
// between packet semantics and the existing 8-bit ready/valid datapath.
module lsc1_stream_adapter (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         abort,
    input  wire         start,
    input  wire [7:0]   operation,
    input  wire [127:0] operand_a,
    input  wire [127:0] operand_b,
    output wire         busy,
    output reg          done_pulse,
    output reg          fault,
    output reg  [127:0] result,
    output wire [2:0]   arch_state,
    output wire [7:0]   arch_operation,
    output wire [5:0]   arch_payload_index,
    output wire [4:0]   arch_result_index
);
    localparam [7:0] OP_XOR = 8'h01, OP_MUL = 8'h02, OP_SET = 8'h03;
    localparam [2:0] S_IDLE = 3'd0, S_CLEAR = 3'd1,
                     S_COMMAND = 3'd2, S_PAYLOAD = 3'd3,
                     S_RESULT = 3'd4;

    reg [2:0] state;
    reg [7:0] saved_operation;
    reg [127:0] saved_a, saved_b;
    reg [5:0] payload_index;
    reg [4:0] result_index;

    reg [7:0] core_rx_data;
    reg core_rx_valid;
    wire core_rx_ready;
    wire [7:0] core_tx_data;
    wire core_tx_valid;
    wire core_busy, core_done, core_fault;
    // SET and XOR are streaming transforms: their output handshakes occur on
    // the same edge as the corresponding payload byte.  MUL emits only after
    // all 32 operand bytes have been accepted.
    wire core_tx_ready = state == S_PAYLOAD || state == S_RESULT;
    wire core_rx_fire = core_rx_valid && core_rx_ready;
    wire core_tx_fire = core_tx_valid && core_tx_ready;

    leanvm_b_stream_alu datapath (
        .clk(clk), .rst_n(rst_n), .abort(abort),
        .rx_data(core_rx_data), .rx_valid(core_rx_valid),
        .rx_ready(core_rx_ready),
        .tx_data(core_tx_data), .tx_valid(core_tx_valid),
        .tx_ready(core_tx_ready),
        .busy(core_busy), .done_pulse(core_done), .fault(core_fault)
    );

    assign busy = state != S_IDLE;
    assign arch_state = state; assign arch_operation = saved_operation;
    assign arch_payload_index = payload_index; assign arch_result_index = result_index;

    always @(*) begin
        core_rx_valid = 1'b0;
        core_rx_data = 8'h00;
        if (state == S_CLEAR) begin
            core_rx_valid = 1'b1;
            core_rx_data = 8'h7d;
        end else if (state == S_COMMAND) begin
            core_rx_valid = 1'b1;
            core_rx_data = saved_operation;
        end else if (state == S_PAYLOAD) begin
            core_rx_valid = 1'b1;
            case (saved_operation)
                OP_SET: core_rx_data = saved_a[payload_index*8 +: 8];
                OP_XOR: begin
                    if (payload_index[0] == 1'b0)
                        core_rx_data = saved_a[(payload_index >> 1)*8 +: 8];
                    else
                        core_rx_data = saved_b[(payload_index >> 1)*8 +: 8];
                end
                default: begin
                    if (payload_index < 16)
                        core_rx_data = saved_a[payload_index*8 +: 8];
                    else
                        core_rx_data = saved_b[(payload_index-16)*8 +: 8];
                end
            endcase
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= S_IDLE;
            saved_operation <= 0;
            saved_a <= 0;
            saved_b <= 0;
            payload_index <= 0;
            result_index <= 0;
            result <= 0;
            done_pulse <= 1'b0;
            fault <= 1'b0;
        end else if (abort) begin
            state <= S_IDLE;
            payload_index <= 0;
            result_index <= 0;
            result <= 0;
            done_pulse <= 1'b0;
            fault <= 1'b1;
        end else begin
            done_pulse <= 1'b0;
            if (state == S_RESULT && core_fault)
                fault <= 1'b1;

            case (state)
                S_IDLE: begin
                    if (start) begin
                        saved_operation <= operation;
                        saved_a <= operand_a;
                        saved_b <= operand_b;
                        payload_index <= 0;
                        result_index <= 0;
                        result <= 0;
                        fault <= 1'b0;
                        if (operation == OP_XOR || operation == OP_MUL ||
                            operation == OP_SET)
                            state <= S_CLEAR;
                        else begin
                            state <= S_IDLE;
                            fault <= 1'b1;
                            done_pulse <= 1'b1;
                        end
                    end
                end
                S_CLEAR: begin
                    if (core_rx_fire)
                        state <= S_COMMAND;
                end
                S_COMMAND: begin
                    if (core_rx_fire) begin
                        payload_index <= 0;
                        state <= S_PAYLOAD;
                    end
                end
                S_PAYLOAD: begin
                    if (core_tx_fire) begin
                        result[result_index*8 +: 8] <= core_tx_data;
                        result_index <= result_index + 1'b1;
                    end
                    if (core_rx_fire) begin
                        if ((saved_operation == OP_SET && payload_index == 15) ||
                            (saved_operation != OP_SET && payload_index == 31)) begin
                            if (saved_operation == OP_MUL) begin
                                result_index <= 0;
                                state <= S_RESULT;
                            end else begin
                                // SET and XOR transfer their sixteenth result
                                // byte atomically with this final input byte.
                                state <= S_IDLE;
                                done_pulse <= 1'b1;
                            end
                        end else begin
                            payload_index <= payload_index + 1'b1;
                        end
                    end
                end
                S_RESULT: begin
                    if (core_tx_fire) begin
                        result[result_index*8 +: 8] <= core_tx_data;
                        if (result_index == 15) begin
                            state <= S_IDLE;
                            done_pulse <= 1'b1;
                        end else begin
                            result_index <= result_index + 1'b1;
                        end
                    end
                end
                default: state <= S_IDLE;
            endcase
        end
    end

    wire _unused = &{core_busy, core_done, 1'b0};
endmodule

`default_nettype wire

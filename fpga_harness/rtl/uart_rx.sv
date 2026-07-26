`default_nettype none
module uart_rx #(
    parameter integer CLKS_PER_BIT = 217
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       serial_in,
    output reg  [7:0] data,
    output reg        valid,
    input  wire       ready,
    output reg        framing_error,
    output reg        overflow
);
    localparam [1:0] IDLE = 2'd0, START = 2'd1, BITS = 2'd2, STOP = 2'd3;
    reg sync_1, sync_2;
    reg [1:0] state;
    integer count;
    reg [2:0] bit_index;
    reg [7:0] shift;

    always @(posedge clk) begin
        sync_1 <= serial_in;
        sync_2 <= sync_1;
        if (!rst_n) begin
            sync_1 <= 1'b1;
            sync_2 <= 1'b1;
            state <= IDLE;
            count <= 0;
            bit_index <= 3'b0;
            shift <= 8'b0;
            data <= 8'b0;
            valid <= 1'b0;
            framing_error <= 1'b0;
            overflow <= 1'b0;
        end else begin
            if (valid && ready)
                valid <= 1'b0;
            case (state)
                IDLE: if (!sync_2) begin
                    count <= (CLKS_PER_BIT / 2) - 1;
                    state <= START;
                end
                START: if (count == 0) begin
                    if (!sync_2) begin
                        count <= CLKS_PER_BIT - 1;
                        bit_index <= 3'b0;
                        state <= BITS;
                    end else begin
                        state <= IDLE;
                    end
                end else count <= count - 1;
                BITS: if (count == 0) begin
                    shift[bit_index] <= sync_2;
                    count <= CLKS_PER_BIT - 1;
                    if (bit_index == 3'd7)
                        state <= STOP;
                    else
                        bit_index <= bit_index + 1'b1;
                end else count <= count - 1;
                STOP: if (count == 0) begin
                    if (!sync_2)
                        framing_error <= 1'b1;
                    else if (!valid || ready) begin
                        data <= shift;
                        valid <= 1'b1;
                    end else begin
                        overflow <= 1'b1;
                    end
                    state <= IDLE;
                end else count <= count - 1;
                default: state <= IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire

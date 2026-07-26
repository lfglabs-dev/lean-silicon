`default_nettype none
module uart_tx #(
    parameter integer CLKS_PER_BIT = 217
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] data,
    input  wire       valid,
    output wire       ready,
    output reg        serial_out
);
    reg busy;
    reg [9:0] frame;
    reg [3:0] bit_index;
    integer count;
    assign ready = !busy;

    always @(posedge clk) begin
        if (!rst_n) begin
            busy <= 1'b0;
            frame <= 10'h3ff;
            bit_index <= 4'b0;
            count <= 0;
            serial_out <= 1'b1;
        end else if (!busy) begin
            serial_out <= 1'b1;
            if (valid) begin
                frame <= {1'b1, data, 1'b0};
                bit_index <= 4'b0;
                count <= CLKS_PER_BIT - 1;
                serial_out <= 1'b0;
                busy <= 1'b1;
            end
        end else if (count == 0) begin
            count <= CLKS_PER_BIT - 1;
            if (bit_index == 4'd9) begin
                busy <= 1'b0;
                serial_out <= 1'b1;
            end else begin
                bit_index <= bit_index + 1'b1;
                serial_out <= frame[bit_index + 1'b1];
            end
        end else begin
            count <= count - 1;
        end
    end
endmodule
`default_nettype wire

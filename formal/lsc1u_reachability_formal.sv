`default_nettype none

module lsc1u_reachability_formal #(
    parameter [1:0] SELECTED_OP = 0
);
    (* gclk *) reg clk;
    reg rst_n = 1'b0;
    reg started = 1'b0;
    wire [1:0] selected_op = SELECTED_OP;

    wire [7:0] command =
        selected_op == 0 ? 8'h01 :
        selected_op == 1 ? 8'h02 :
        selected_op == 2 ? 8'h03 : 8'hff;
    wire rx_ready, tx_valid, done_pulse;
    wire [7:0] tx_data;

    lsc1u_core dut (
        .clk(clk), .rst_n(rst_n), .ena(1'b1),
        .rx_data(started ? 8'h01 : command),
        .rx_valid(1'b1), .rx_ready(rx_ready),
        .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(1'b1),
        .busy(), .fault(), .done_pulse(done_pulse)
    );

    always @(posedge clk) begin
        rst_n <= 1'b1;
        if (rst_n && rx_ready)
            started <= 1'b1;
        cover(done_pulse);
    end
endmodule

`default_nettype wire

/* Immediate framing-fault property from the frozen v1 packet model. */
`default_nettype none
module b1_packet_rx_fault_formal;
    reg clk = 0, rst_n = 0;
    reg [2:0] phase = 0;
    always @($global_clock) clk <= ~clk;
    wire rx_valid = phase == 1;
    wire fault_valid;
    wire [7:0] fault_status;
    lsc1_packet_rx dut (
        .clk(clk), .rst_n(rst_n), .abort(1'b0), .rx_data(8'h00), .rx_valid(rx_valid),
        .rx_ready(), .frame_valid(), .frame_ready(1'b1), .frame_opcode(), .frame_length(),
        .frame_payload(), .fault_valid(fault_valid), .fault_status(fault_status), .busy()
    );
    always @(posedge clk) begin
        if (phase == 0) begin rst_n <= 1'b1; phase <= 1; end
        else phase <= phase + 1'b1;
        if (phase == 2) begin
            assert (fault_valid && fault_status == 8'h80); // BAD_SOF
            cover (fault_valid);
        end
    end
endmodule
`default_nettype wire

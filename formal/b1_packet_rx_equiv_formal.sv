/* B1 closed-frame equivalence harness for the frozen v1 request envelope. */
`default_nettype none

module b1_packet_rx_equiv_formal;
    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg [4:0] phase = 0;
    localparam [7:0] opcode = 8'h13;  // STATUS query, frozen v1 opcode
    always @($global_clock) clk <= ~clk;

    wire [7:0] request_byte =
        phase == 1 ? 8'ha1 : phase == 2 ? 8'h01 :
        phase == 3 ? opcode : phase == 4 ? 8'h00 :
        phase == 5 ? 8'h00 : phase == 6 ? 8'h00 :
        phase == 7 ? 8'h29 : phase == 8 ? 8'hb2 :
        phase == 9 ? 8'h4e : 8'h1c;
    wire rx_valid = phase >= 1 && phase <= 10;

    wire [7:0] bad_crc_byte = phase == 10 ? request_byte ^ 8'h01 : request_byte;
    /* Same bad CRC plus bad version: CRC precedence is frozen model behaviour. */
    wire [7:0] precedence_byte = phase == 2 ? 8'h02 : bad_crc_byte;

    wire good_ready, good_frame, good_fault, bad_frame, bad_fault, pre_frame, pre_fault;
    wire [7:0] good_opcode, bad_status, pre_status;
    wire [15:0] good_length;
    wire [2047:0] ignored_payload;

    lsc1_packet_rx good (
        .clk(clk), .rst_n(rst_n), .abort(1'b0), .rx_data(request_byte), .rx_valid(rx_valid),
        .rx_ready(good_ready), .frame_valid(good_frame), .frame_ready(1'b1),
        .frame_opcode(good_opcode), .frame_length(good_length), .frame_payload(ignored_payload),
        .fault_valid(good_fault), .fault_status(), .busy()
    );
    lsc1_packet_rx bad (
        .clk(clk), .rst_n(rst_n), .abort(1'b0), .rx_data(bad_crc_byte), .rx_valid(rx_valid),
        .rx_ready(), .frame_valid(bad_frame), .frame_ready(1'b1), .frame_opcode(), .frame_length(),
        .frame_payload(), .fault_valid(bad_fault), .fault_status(bad_status), .busy()
    );
    lsc1_packet_rx precedence (
        .clk(clk), .rst_n(rst_n), .abort(1'b0), .rx_data(precedence_byte), .rx_valid(rx_valid),
        .rx_ready(), .frame_valid(pre_frame), .frame_ready(1'b1), .frame_opcode(), .frame_length(),
        .frame_payload(), .fault_valid(pre_fault), .fault_status(pre_status), .busy()
    );

    always @(posedge clk) begin
        if (phase == 0) begin rst_n <= 1'b1; phase <= 1; end
        else if (phase < 12) phase <= phase + 1'b1;
        if (phase >= 1 && phase <= 10) assert (good_ready);
        if (phase == 11) begin
            assert (good_frame && !good_fault);
            assert (good_opcode == opcode && good_length == 0);
            assert (bad_fault && !bad_frame && bad_status == 8'h84);
            assert (pre_fault && !pre_frame && pre_status == 8'h84);
            cover (good_frame && bad_fault && pre_fault);
        end
    end
endmodule

`default_nettype wire

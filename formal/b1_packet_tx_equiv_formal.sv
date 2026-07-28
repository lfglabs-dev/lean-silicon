/*
 * B1 packet-TX equivalence harness.
 *
 * This is a cycle-level reference for the v1 response envelope defined by
 * docs/LSC1_PROTOCOL.md and implemented by sim/lsc1_transaction.py:
 *     5a 01 status length-lo length-hi payload crc32-le
 *
 * The payload-bearing BAD_CRC response below is a frozen model vector;
 * The formal trace accepts every beat, so it proves the complete exact
 * byte/CRC sequence.  Backpressure stability is checked separately by the
 * executable test in formal/b1_packet_equiv_test.py.
 */
`default_nettype none

module b1_packet_tx_equiv_formal;
    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg started = 1'b0;
    localparam [7:0] status = 8'h84;  // BAD_CRC in the frozen model
    localparam [7:0] payload0 = 8'hde;
    localparam [7:0] payload1 = 8'had;
    wire tx_ready = 1'b1;

    always @($global_clock) clk <= ~clk;
    always @(posedge clk) begin
        rst_n <= 1'b1;
        if (rst_n) started <= 1'b1;
    end

    wire start = rst_n && !started;
    wire [543:0] payload = {528'd0, payload1, payload0};
    wire busy, done_pulse, tx_valid;
    wire [7:0] tx_data;
    wire [31:0] payload_crc;

    lsc1_packet_tx dut (
        .clk(clk), .rst_n(rst_n), .abort(1'b0), .start(start),
        .status(status), .payload_length(16'd2), .payload(payload),
        .busy(busy), .done_pulse(done_pulse), .payload_crc(payload_crc),
        .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(tx_ready)
    );

    reg ref_active = 1'b0;
    reg [3:0] ref_index = 4'd0;
    reg ref_done = 1'b0;
    reg [7:0] expected_byte;

    always @(*) begin
        case (ref_index)
            0: expected_byte = 8'h5a;
            1: expected_byte = 8'h01;
            2: expected_byte = status;
            3: expected_byte = 8'h02;
            4: expected_byte = 8'h00;
            5: expected_byte = payload0;
            6: expected_byte = payload1;
            7: expected_byte = 8'h3f;
            8: expected_byte = 8'h53;
            9: expected_byte = 8'h26;
            default: expected_byte = 8'h88;
        endcase
    end

    always @(posedge clk) begin
        ref_done <= 1'b0;
        if (!rst_n) begin
            ref_active <= 1'b0;
            ref_index <= 0;
        end else if (start && !ref_active) begin
            ref_active <= 1'b1;
            ref_index <= 0;
        end else if (ref_active && tx_ready) begin
            if (ref_index == 10) begin
                ref_active <= 1'b0;
                ref_done <= 1'b1;
            end else
                ref_index <= ref_index + 1'b1;
        end

        if (rst_n) begin
            assert (busy == ref_active);
            assert (tx_valid == ref_active);
            assert (!ref_active || tx_data == expected_byte);
            assert (done_pulse == ref_done);
            if ($past(rst_n) && $past(tx_valid) && !$past(tx_ready)) begin
                assert (tx_valid);
                assert (tx_data == $past(tx_data));
            end
            if (ref_done) cover (1'b1);
        end
    end
endmodule

`default_nettype wire

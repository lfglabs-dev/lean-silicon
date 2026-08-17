`timescale 1ns/1ps
`default_nettype none

module tb_lsc1_packet_rx_payload_prefix;
    reg clk = 0;
    always #5 clk = ~clk;

    reg rst_n = 0;
    reg abort = 0;
    reg [7:0] rx_data = 0;
    reg rx_valid = 0;
    wire rx_ready;
    wire frame_valid;
    reg frame_ready = 0;
    wire [7:0] frame_opcode;
    wire [15:0] frame_length;
    wire [2047:0] frame_payload;
    wire fault_valid;
    wire [7:0] fault_status;
    wire busy;
    integer i;

    lsc1_packet_rx dut (
        .clk(clk), .rst_n(rst_n), .abort(abort),
        .rx_data(rx_data), .rx_valid(rx_valid), .rx_ready(rx_ready),
        .frame_valid(frame_valid), .frame_ready(frame_ready),
        .frame_opcode(frame_opcode), .frame_length(frame_length),
        .frame_payload(frame_payload), .fault_valid(fault_valid),
        .fault_status(fault_status), .busy(busy)
    );

    function automatic [7:0] payload_byte(input integer index);
        payload_byte = index[7:0] ^ 8'ha5;
    endfunction

    function automatic [31:0] crc_byte(input [31:0] crc_in, input [7:0] data);
        integer bit_index;
        reg [31:0] work;
        begin
            work = crc_in ^ data;
            for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1)
                work = work[0] ? ((work >> 1) ^ 32'hedb88320) : (work >> 1);
            crc_byte = work;
        end
    endfunction

    task automatic send_beat(input [7:0] value);
        begin
            @(negedge clk);
            rx_data = value;
            rx_valid = 1;
            do @(posedge clk); while (!rx_ready);
            @(negedge clk);
            rx_valid = 0;
        end
    endtask

    task automatic send_frame(
        input integer length,
        input integer mutated_index,
        input integer crc_tracks_mutation
    );
        integer index;
        reg [7:0] baseline;
        reg [7:0] transmitted;
        reg [31:0] crc;
        begin
            crc = 32'hffffffff;
            send_beat(8'ha1); crc = crc_byte(crc, 8'ha1);
            send_beat(8'h01); crc = crc_byte(crc, 8'h01);
            send_beat(8'h08); crc = crc_byte(crc, 8'h08);
            send_beat(8'h00); crc = crc_byte(crc, 8'h00);
            send_beat(length[7:0]); crc = crc_byte(crc, length[7:0]);
            send_beat(length[15:8]); crc = crc_byte(crc, length[15:8]);
            for (index = 0; index < length; index = index + 1) begin
                baseline = payload_byte(index);
                transmitted = (index == mutated_index) ? (baseline ^ 8'h01) : baseline;
                send_beat(transmitted);
                crc = crc_byte(crc, crc_tracks_mutation ? transmitted : baseline);
            end
            crc = ~crc;
            send_beat(crc[7:0]);
            send_beat(crc[15:8]);
            send_beat(crc[23:16]);
            send_beat(crc[31:24]);
        end
    endtask

    task automatic accept_frame(input integer expected_length);
        begin
            if (!frame_valid || fault_valid || frame_opcode !== 8'h08 ||
                frame_length !== expected_length[15:0])
                $fatal(1, "length %0d was not accepted byte-exactly", expected_length);
            for (i = 0; i < 190; i = i + 1)
                if (frame_payload[i*8 +: 8] !== payload_byte(i))
                    $fatal(1, "stored prefix mismatch at byte %0d", i);
            if (frame_payload[2047:1520] !== 528'b0)
                $fatal(1, "upper 528 interface bits are not constant zero");
            @(negedge clk); frame_ready = 1;
            @(posedge clk);
            @(negedge clk); frame_ready = 0;
        end
    endtask

    task automatic accept_bad_crc;
        begin
            if (!fault_valid || frame_valid || fault_status !== 8'h84)
                $fatal(1, "discarded-tail mutation did not produce BAD_CRC");
            @(negedge clk); frame_ready = 1;
            @(posedge clk);
            @(negedge clk); frame_ready = 0;
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        @(negedge clk); rst_n = 1;

        send_frame(190, -1, 1); accept_frame(190);
        send_frame(191, -1, 1); accept_frame(191);
        send_frame(255, -1, 1); accept_frame(255);
        send_frame(256, -1, 1); accept_frame(256);

        // Bytes outside registered storage remain part of framing integrity.
        send_frame(191, 190, 0); accept_bad_crc();
        send_frame(256, 255, 0); accept_bad_crc();

        // The existing maximum remains 256 and rejects 257 at the header.
        send_beat(8'ha1); send_beat(8'h01); send_beat(8'h08);
        send_beat(8'h00); send_beat(8'h01); send_beat(8'h01);
        if (!fault_valid || fault_status !== 8'h83)
            $fatal(1, "257-byte declaration did not produce BAD_LENGTH");

        $display("PASS: 190-byte prefix storage, 191/255/256 consumption, tail CRC, and 257 limit");
        $finish;
    end
endmodule

`default_nettype wire

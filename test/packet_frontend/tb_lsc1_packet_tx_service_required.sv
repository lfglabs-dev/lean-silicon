`timescale 1ns/1ps
`default_nettype none

module tb_lsc1_packet_tx_service_required;
    localparam integer PAYLOAD_BYTES = 122;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, abort = 0, start = 0;
    reg [7:0] status = 8'h01;
    reg [15:0] payload_length = PAYLOAD_BYTES;
    reg [159:0] payload = 0;
    reg payload_external = 1;
    wire [15:0] payload_index;
    wire payload_external_valid;
    reg [7:0] source [0:PAYLOAD_BYTES-1];
    wire [7:0] payload_external_data =
        payload_index < PAYLOAD_BYTES ? source[payload_index] : 8'h00;
    wire busy, done_pulse, tx_valid;
    wire [31:0] payload_crc;
    wire [7:0] tx_data;
    reg tx_ready = 0;
    reg [7:0] response [0:130];
    integer count = 0, cycle = 0, i;
    reg [7:0] stalled_data;
    reg [15:0] stalled_index;
    reg [31:0] expected_crc, expected_payload_crc;

    lsc1_packet_tx dut (
        .clk(clk), .rst_n(rst_n), .abort(abort), .start(start),
        .status(status), .payload_length(payload_length), .payload(payload),
        .payload_external(payload_external), .payload_index(payload_index),
        .payload_external_valid(payload_external_valid),
        .payload_external_data(payload_external_data), .busy(busy),
        .done_pulse(done_pulse), .payload_crc(payload_crc),
        .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(tx_ready)
    );

    function automatic [31:0] crc_byte;
        input [31:0] crc_in;
        input [7:0] data;
        integer bit_index;
        reg [31:0] work;
        begin
            work = crc_in ^ data;
            for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1)
                work = work[0] ? ((work >> 1) ^ 32'hedb88320) : (work >> 1);
            crc_byte = work;
        end
    endfunction

    always @(posedge clk) begin
        cycle <= cycle + 1;
        if (tx_valid && tx_ready) begin
            response[count] <= tx_data;
            count <= count + 1;
        end
        if (cycle > 10000) $fatal(1, "serializer timeout");
    end

    initial begin
        // Distinct deterministic bytes exercise all 122 externally sourced beats.
        for (i = 0; i < PAYLOAD_BYTES; i = i + 1)
            source[i] = (i * 8'h3d) ^ (i >> 1) ^ 8'ha7;
        repeat (3) @(posedge clk);
        if (tx_valid || payload_external_valid)
            $fatal(1, "reset exposed a transfer or external source reference");
        rst_n = 1;
        @(negedge clk); start = 1;
        @(negedge clk); start = 0;

        // Stall every response byte for a varying nonzero interval.  Both the
        // selected source byte and its scatter/gather index must remain stable.
        while (!done_pulse) begin
            wait (tx_valid);
            @(negedge clk);
            stalled_data = tx_data;
            stalled_index = payload_index;
            if (count >= 5 && count < 5 + PAYLOAD_BYTES) begin
                if (!payload_external_valid || payload_index != count - 5)
                    $fatal(1, "missing/bad external source reference at beat %0d", count);
            end else if (payload_external_valid || payload_index != 0) begin
                $fatal(1, "external source referenced outside payload at beat %0d", count);
            end
            tx_ready = 0;
            repeat ((count % 5) + 1) begin
                @(posedge clk); #1;
                if (!tx_valid || tx_data !== stalled_data ||
                    payload_index !== stalled_index ||
                    payload_external_valid !==
                        (count >= 5 && count < 5 + PAYLOAD_BYTES))
                    $fatal(1, "external payload changed under stall at beat %0d", count);
            end
            @(negedge clk); tx_ready = 1;
            @(posedge clk);
            @(negedge clk); tx_ready = 0;
        end

        if (count != 131) $fatal(1, "response length got=%0d expected=131", count);
        if (response[0] !== 8'h5a || response[1] !== 8'h01 ||
            response[2] !== 8'h01 || response[3] !== 8'h7a ||
            response[4] !== 8'h00)
            $fatal(1, "SERVICE_REQUIRED header mismatch");
        for (i = 0; i < PAYLOAD_BYTES; i = i + 1)
            if (response[5+i] !== source[i])
                $fatal(1, "SERVICE_REQUIRED payload mismatch at byte %0d", i);

        expected_crc = 32'hffffffff;
        for (i = 0; i < 5 + PAYLOAD_BYTES; i = i + 1)
            expected_crc = crc_byte(expected_crc, response[i]);
        expected_crc = ~expected_crc;
        if ({response[130], response[129], response[128], response[127]} !== expected_crc)
            $fatal(1, "SERVICE_REQUIRED envelope CRC mismatch");
        expected_payload_crc = 32'hffffffff;
        for (i = 0; i < PAYLOAD_BYTES; i = i + 1)
            expected_payload_crc = crc_byte(expected_payload_crc, source[i]);
        expected_payload_crc = ~expected_payload_crc;
        if (payload_crc !== expected_payload_crc)
            $fatal(1, "SERVICE_REQUIRED payload CRC mismatch");

        // ABORT invalidates an external source transfer on the same edge.
        @(negedge clk); start = 1; tx_ready = 1;
        @(posedge clk);
        @(negedge clk); start = 0;
        wait (payload_external_valid);
        @(negedge clk); tx_ready = 0;
        #1;
        if (!payload_external_valid)
            $fatal(1, "abort precondition did not reach an external payload beat");
        abort = 1;
        #1;
        if (tx_valid || payload_external_valid)
            $fatal(1, "abort did not invalidate same-edge transfer/source reference");
        @(posedge clk); #1;
        if (tx_valid || payload_external_valid || busy || done_pulse)
            $fatal(1, "abort did not invalidate external payload transfer");

        // Reset has the same immediate invalidation contract while active.
        @(negedge clk); abort = 0; start = 1; tx_ready = 1;
        @(posedge clk);
        @(negedge clk); start = 0;
        wait (payload_external_valid);
        @(negedge clk); tx_ready = 0;
        #1;
        if (!payload_external_valid)
            $fatal(1, "reset precondition did not reach an external payload beat");
        rst_n = 0;
        #1;
        if (tx_valid || payload_external_valid)
            $fatal(1, "reset did not invalidate same-edge transfer/source reference");
        @(posedge clk); #1;
        if (tx_valid || payload_external_valid || busy || done_pulse)
            $fatal(1, "reset did not invalidate active external payload transfer");
        $display("PASS: immutable 122-byte SERVICE_REQUIRED transport, CRC, and every-beat stalls");
        $finish;
    end
endmodule

`default_nettype wire

`timescale 1ns/1ps
`default_nettype none

module tb_lsc1_packet_frontend;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, abort = 0;
    reg [7:0] rx_data = 0;
    reg rx_valid = 0;
    wire rx_ready;
    wire [7:0] tx_data;
    wire tx_valid;
    reg tx_ready = 1;
    wire busy, fault, done_pulse;

    reg [7:0] payload [0:255];
    reg [7:0] response [0:255];
    integer response_count = 0;
    integer done_count = 0;
    integer cycle_count = 0;
    integer i;
    reg [7:0] held_tx_byte;
    reg [31:0] saved_result_crc;
    integer saved_result_length;

    lsc1_packet_frontend dut (
        .clk(clk), .rst_n(rst_n), .abort(abort),
        .rx_data(rx_data), .rx_valid(rx_valid), .rx_ready(rx_ready),
        .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(tx_ready),
        .busy(busy), .fault(fault), .done_pulse(done_pulse)
    );

    always @(posedge clk) begin
        cycle_count <= cycle_count + 1;
        if (rst_n && dut.tx_start && !busy)
            $fatal(1, "BUSY dropped while a response was queued");
        if (tx_valid && tx_ready) begin
            response[response_count] <= tx_data;
            response_count <= response_count + 1;
        end
        if (done_pulse) done_count <= done_count + 1;
    end

    function automatic [31:0] crc_byte;
        input [31:0] crc_in;
        input [7:0] data;
        integer k;
        reg [31:0] work;
        begin
            work = crc_in ^ data;
            for (k = 0; k < 8; k = k + 1)
                work = work[0] ? ((work >> 1) ^ 32'hedb88320) : work >> 1;
            crc_byte = work;
        end
    endfunction

    task automatic clear_payload;
        begin
            for (i = 0; i < 256; i = i + 1) payload[i] = 0;
        end
    endtask

    task automatic put_u32(input integer at, input [31:0] value);
        begin
            payload[at] = value[7:0]; payload[at+1] = value[15:8];
            payload[at+2] = value[23:16]; payload[at+3] = value[31:24];
        end
    endtask

    task automatic send_beat(input [7:0] value, input integer stall);
        begin
            repeat (stall) @(posedge clk);
            @(negedge clk);
            rx_data = value;
            rx_valid = 1;
            do @(posedge clk); while (!rx_ready);
            @(negedge clk);
            rx_valid = 0;
        end
    endtask

    task automatic send_frame(
        input [7:0] version, input [7:0] opcode, input [7:0] flags,
        input integer length, input integer corrupt_crc
    );
        reg [31:0] crc;
        integer k;
        begin
            crc = 32'hffffffff;
            send_beat(8'ha1, 0); crc = crc_byte(crc, 8'ha1);
            send_beat(version, 1); crc = crc_byte(crc, version);
            send_beat(opcode, 0); crc = crc_byte(crc, opcode);
            send_beat(flags, 1); crc = crc_byte(crc, flags);
            send_beat(length[7:0], 0); crc = crc_byte(crc, length[7:0]);
            send_beat(length[15:8], 1); crc = crc_byte(crc, length[15:8]);
            for (k = 0; k < length; k = k + 1) begin
                send_beat(payload[k], k & 1);
                crc = crc_byte(crc, payload[k]);
            end
            crc = ~crc;
            if (corrupt_crc) crc = crc ^ 1;
            send_beat(crc[7:0], 0); send_beat(crc[15:8], 1);
            send_beat(crc[23:16], 0); send_beat(crc[31:24], 1);
        end
    endtask

    task automatic wait_response(input [7:0] expected_status);
        integer total, guard, length;
        reg [31:0] crc;
        begin
            guard = 0;
            while (response_count < 5) begin
                @(posedge clk); guard = guard + 1;
                if (guard > 2000) $fatal(1, "response header timeout");
            end
            length = response[3] | (response[4] << 8);
            total = 5 + length + 4;
            while (response_count < total) begin
                @(posedge clk); guard = guard + 1;
                if (guard > 4000) $fatal(1, "response body timeout");
            end
            if (response[0] !== 8'h5a || response[1] !== 1 ||
                response[2] !== expected_status)
                $fatal(1, "status got=%02x expected=%02x", response[2], expected_status);
            crc = 32'hffffffff;
            for (i = 0; i < total-4; i = i + 1) crc = crc_byte(crc, response[i]);
            crc = ~crc;
            if ({response[total-1],response[total-2],response[total-3],response[total-4]} !== crc)
                $fatal(1, "response CRC mismatch");
            @(negedge clk);
            response_count = 0;
        end
    endtask

    task automatic build_set(input [31:0] txn, input [31:0] pc, input [31:0] fp);
        begin
            clear_payload();
            put_u32(0, txn); put_u32(4, pc); put_u32(8, fp);
            payload[12] = 1; payload[13] = 0; put_u32(14, 7);
            for (i = 0; i < 16; i = i + 1) payload[18+i] = 8'h40 + i;
            payload[34] = 0;
        end
    endtask

    task automatic build_binary(
        input [31:0] txn, input [31:0] pc, input [7:0] opcode
    );
        begin
            clear_payload();
            put_u32(0, txn); put_u32(4, pc); put_u32(8, 0);
            payload[12] = 1; payload[13] = 0;
            put_u32(14, 1); put_u32(18, 2); put_u32(22, 3);
            payload[26] = 1; payload[43] = 1; payload[60] = 0;
            if (opcode == 8'h01) begin
                payload[27] = 8'h55;
                payload[44] = 8'haa;
            end else begin
                // x^127 * x reduces to 0x87.
                payload[27+15] = 8'h80;
                payload[44] = 8'h02;
                payload[77] = 0;
            end
        end
    endtask

    task automatic retire_last(input [31:0] txn, input integer corrupt_result_crc);
        reg [31:0] crc;
        integer length, k;
        begin
            length = response[3] | (response[4] << 8);
            crc = 32'hffffffff;
            for (k = 0; k < length; k = k + 1) crc = crc_byte(crc, response[5+k]);
            crc = ~crc;
            response_count = 0;
            clear_payload(); put_u32(0, txn);
            put_u32(4, corrupt_result_crc ? crc ^ 1 : crc);
            send_frame(1, 8'h12, 0, 8, 0);
        end
    endtask

    initial begin
        repeat (4) @(posedge clk);
        rst_n = 1;
        repeat (2) @(posedge clk);

        // Negotiate the only profile this integrated RTL currently advertises.
        clear_payload();
        payload[0] = 1; payload[1] = 1; payload[2] = 1;
        send_frame(1, 8'h10, 0, 7, 0);
        wait (response_count >= 23);
        if (response[5] !== 1 || response[6] !== 1 ||
            response[7] !== 0 || response[8] !== 1 ||
            response[9] !== 16 || response[10] !== 0 ||
            response[11] !== 6 || response[12] !== 0 ||
            response[13] !== 0 || response[14] !== 0 ||
            response[15] !== 8'h31 || response[16] !== 8'h43 ||
            response[17] !== 8'h53 || response[18] !== 8'h4c)
            $fatal(1, "NEGOTIATE capability payload mismatch");
        wait_response(8'h00);

        // STATUS_QUERY is a non-mutating packet response.
        clear_payload();
        send_frame(1, 8'h13, 0, 0, 0);
        wait (response_count >= 29);
        if (response[5] !== 0 || response[24] !== 0)
            $fatal(1, "initial STATUS state mismatch");
        wait_response(8'h03);

        // Valid SET with deterministic input stalls and output backpressure.
        build_set(32'h11, 0, 4);
        send_frame(1, 8'h03, 0, 51, 0);
        @(negedge clk); tx_ready = 0;
        wait (tx_valid);
        #1; // allow combinational tx_data to settle after active/index update
        held_tx_byte = tx_data;
        repeat (12) begin
            @(posedge clk);
            if (!tx_valid || tx_data !== held_tx_byte || rx_ready) begin
                $display("DEBUG tx_valid=%0d tx_data=%02x held=%02x rx_ready=%0d adapter_state=%0d adapter_result_index=%0d",
                         tx_valid, tx_data, held_tx_byte, rx_ready,
                         dut.adapter.state, dut.adapter.result_index);
                $fatal(1, "output backpressure stability/receive exclusion failed");
            end
        end
        @(negedge clk); tx_ready = 1;
        wait (response_count >= 5);
        if (response[2] !== 0) $fatal(1, "SET not accepted");
        wait (response_count >= 5 + (response[3] | response[4]<<8) + 4);
        if ({response[8],response[7],response[6],response[5]} !== 32'h11 ||
            {response[12],response[11],response[10],response[9]} !== 1 ||
            {response[16],response[15],response[14],response[13]} !== 4 ||
            response[17] !== 1 ||
            {response[21],response[20],response[19],response[18]} !== 11 ||
            response[38] !== 0 || response[39] !== 1 ||
            {response[43],response[42],response[41],response[40]} !== 11)
            $fatal(1, "SET result payload schema mismatch");
        for (i = 0; i < 16; i = i + 1)
            if (response[22+i] !== 8'h40 + i)
                $fatal(1, "SET result write value mismatch at byte %0d", i);
        retire_last(32'h11, 0);
        wait_response(8'h02);
        if (done_count != 1 || dut.retire_seq != 1)
            $fatal(1, "retirement pulse/state not atomic");

        // A transaction can retire at most once.
        clear_payload(); put_u32(0, 32'h11); put_u32(4, 0);
        send_frame(1, 8'h12, 0, 8, 0);
        wait_response(8'h87);

        // Committed state rejects a foreign/rewound request.
        build_set(32'h12, 0, 4);
        send_frame(1, 8'h03, 0, 51, 0);
        wait_response(8'h94);

        // Stage another result; an instruction cannot replace it.
        build_set(32'h13, 1, 4);
        send_frame(1, 8'h03, 0, 51, 0);
        wait (response_count >= 5 + (response[3] | response[4]<<8) + 4);
        saved_result_length = response[3] | (response[4] << 8);
        saved_result_crc = 32'hffffffff;
        for (i = 0; i < saved_result_length; i = i + 1)
            saved_result_crc = crc_byte(saved_result_crc, response[5+i]);
        saved_result_crc = ~saved_result_crc;
        response_count = 0;
        build_set(32'h14, 1, 4);
        send_frame(1, 8'h03, 0, 51, 0);
        wait_response(8'h87);

        // Payload decoding precedes the pending-state guard.  Profile is
        // decoded before flags, and decoder faults have transaction ID zero.
        build_set(32'h14, 1, 4);
        payload[12] = 2;
        payload[13] = 1;
        send_frame(1, 8'h03, 0, 51, 0);
        wait (response_count >= 14);
        if ({response[8],response[7],response[6],response[5]} !== 0)
            $fatal(1, "decoder fault acquired payload transaction ID");
        wait_response(8'h86);
        build_set(32'h14, 1, 4);
        payload[34] = 2;
        send_frame(1, 8'h03, 0, 51, 0);
        wait_response(8'h88);
        clear_payload();
        payload[0] = 2; payload[1] = 2; payload[2] = 2;
        send_frame(1, 8'h10, 0, 7, 0);
        wait_response(8'h86);
        clear_payload();
        payload[0] = 2; payload[1] = 2; payload[2] = 1;
        send_frame(1, 8'h10, 0, 7, 0);
        wait_response(8'h87);

        // Framing is validated before dispatch state; preserve the staged result.
        build_set(32'h14, 1, 4);
        send_frame(1, 8'h03, 0, 50, 0);
        wait_response(8'h83);
        clear_payload(); put_u32(0, 32'h13); put_u32(4, saved_result_crc);
        send_frame(1, 8'h12, 0, 8, 0);
        wait_response(8'h02);

        // Restage before checking that a bad result CRC discards the result.
        build_set(32'h13, 2, 4);
        send_frame(1, 8'h03, 0, 51, 0);
        wait (response_count >= 5 + (response[3] | response[4]<<8) + 4);
        saved_result_length = response[3] | (response[4] << 8);
        saved_result_crc = 32'hffffffff;
        for (i = 0; i < saved_result_length; i = i + 1)
            saved_result_crc = crc_byte(saved_result_crc, response[5+i]);
        saved_result_crc = ~saved_result_crc;
        response_count = 0;

        // Matching txn with bad result CRC discards the staged result.
        clear_payload(); put_u32(0, 32'h13); put_u32(4, saved_result_crc ^ 1);
        send_frame(1, 8'h12, 0, 8, 0);
        wait_response(8'h92);

        // Restage, then prove a foreign RETIRE also discards; retry is BAD_STATE.
        build_set(32'h15, 2, 4);
        send_frame(1, 8'h03, 0, 51, 0);
        wait (response_count >= 5 + (response[3] | response[4]<<8) + 4);
        saved_result_length = response[3] | (response[4] << 8);
        saved_result_crc = 32'hffffffff;
        for (i = 0; i < saved_result_length; i = i + 1)
            saved_result_crc = crc_byte(saved_result_crc, response[5+i]);
        saved_result_crc = ~saved_result_crc;
        response_count = 0;
        clear_payload(); put_u32(0, 32'h99); put_u32(4, saved_result_crc);
        send_frame(1, 8'h12, 0, 8, 0);
        wait_response(8'h92);
        clear_payload(); put_u32(0, 32'h15); put_u32(4, 0);
        send_frame(1, 8'h12, 0, 8, 0);
        wait_response(8'h87);

        // Deterministic framing faults.
        clear_payload(); send_frame(2, 8'h03, 0, 0, 0); wait_response(8'h81);
        clear_payload(); send_frame(1, 8'h7f, 0, 0, 0); wait_response(8'h82);
        clear_payload(); send_frame(1, 8'h03, 0, 50, 0); wait_response(8'h83);
        clear_payload(); send_frame(1, 8'h03, 0, 51, 1); wait_response(8'h84);
        clear_payload(); send_frame(1, 8'h03, 1, 51, 0); wait_response(8'h85);
        send_beat(8'h00, 0); wait_response(8'h80);
        clear_payload();
        send_beat(8'ha1, 0); send_beat(1, 0); send_beat(8'h03, 0);
        send_beat(0, 0); send_beat(1, 0); send_beat(1, 0);
        wait (response_count >= 14);
        if (response[9] !== 1)
            $fatal(1, "oversized header BAD_LENGTH detail mismatch");
        wait_response(8'h83); // 257-byte declaration rejected at the header

        // A truncated frame cannot retire: reset drops it without a response.
        send_beat(8'ha1, 0); send_beat(1, 0); send_beat(8'h03, 0);
        if (!busy) $fatal(1, "partial frame did not assert BUSY");
        @(negedge clk); rst_n = 0;
        repeat (2) @(posedge clk);
        @(negedge clk); rst_n = 1;
        repeat (2) @(posedge clk);
        if (response_count != 0 || busy) $fatal(1, "reset retained partial packet");

        // ABORT cancels a partial packet without emitting a response.
        send_beat(8'ha1, 0); send_beat(1, 0);
        @(negedge clk); abort = 1;
        @(posedge clk);
        @(negedge clk); abort = 0;
        repeat (12) @(posedge clk);
        if (response_count != 0 || busy || tx_valid)
            $fatal(1, "ABORT emitted a response for a partial packet");
        if (dut.retire_seq != 0) $fatal(1, "reset/abort changed retirement state");

        // ABORT also discards a queued result response and its staged result.
        @(negedge clk); tx_ready = 0;
        build_set(32'h20, 0, 0);
        send_frame(1, 8'h03, 0, 51, 0);
        wait (tx_valid);
        @(negedge clk); abort = 1;
        @(posedge clk);
        @(negedge clk); abort = 0;
        tx_ready = 1;
        repeat (12) @(posedge clk);
        if (response_count != 0 || busy || tx_valid || dut.result_pending)
            $fatal(1, "ABORT retained or emitted a pending response");

        // Exercise the two other owned opcodes and check their staged writes.
        build_binary(32'h21, 0, 8'h01);
        send_frame(1, 8'h01, 0, 77, 0);
        wait (response_count >= 5 + (response[3] | response[4]<<8) + 4);
        if (response[17] !== 1 || response[22] !== 8'hff)
            $fatal(1, "XOR result payload mismatch");
        retire_last(32'h21, 0);
        wait_response(8'h02);

        build_binary(32'h22, 1, 8'h02);
        send_frame(1, 8'h02, 0, 94, 0);
        wait (dut.compute_state != 0);
        if (rx_ready) $fatal(1, "RX_READY high during MUL decision");
        wait (response_count >= 5 + (response[3] | response[4]<<8) + 4);
        if (response[17] !== 1 || response[22] !== 8'h87)
            $fatal(1, "MUL result payload mismatch");
        for (i = 1; i < 16; i = i + 1)
            if (response[22+i] !== 0) $fatal(1, "MUL high byte %0d nonzero", i);
        retire_last(32'h22, 0);
        wait_response(8'h02);

        // Interpreter-compatible MUL backsolve: missing A = C * inverse(B).
        clear_payload();
        put_u32(0, 32'h23); put_u32(4, 2); put_u32(8, 0);
        payload[12] = 1;
        put_u32(14, 1); put_u32(18, 2); put_u32(22, 3);
        payload[26] = 0;              // A absent
        payload[43] = 1; payload[44] = 1; // B = 1
        payload[60] = 1; payload[61] = 5; // C = 5
        payload[77] = 1; payload[78] = 1; // inverse(B) = 1
        send_frame(1, 8'h02, 0, 94, 0);
        wait (response_count >= 5 + (response[3] | response[4]<<8) + 4);
        if (response[17] !== 1 || response[22] !== 5)
            $fatal(1, "MUL backsolve result mismatch");
        retire_last(32'h23, 0);
        wait_response(8'h02);
        if (done_count != 5 || dut.retire_seq != 3)
            $fatal(1, "DONE count disagrees with successful retirements");

        $display("PASS: LSC-1 Phase-3 packet frontend adversarial test");
        $finish;
    end
endmodule

`default_nettype wire

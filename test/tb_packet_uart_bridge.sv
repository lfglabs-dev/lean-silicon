`timescale 1ns/1ps
`default_nettype none

module tb_packet_uart_bridge;
    localparam integer BIT_NS = 1000;
    reg clk = 0;
    always #20 clk = ~clk;
    reg uart_rx = 1;
    wire uart_tx;

    uart_bridge #(.PACKET_MODE(1'b1)) dut (
        .clk(clk), .uart_rx(uart_rx), .uart_tx(uart_tx)
    );

    reg [7:0] payload [0:255];
    reg [7:0] response [0:255];
    integer response_count = 0;
    integer errors = 0;
    integer i;

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

    task automatic send_byte(input [7:0] value);
        integer k;
        begin
            uart_rx = 0; #(BIT_NS);
            for (k = 0; k < 8; k = k + 1) begin
                uart_rx = value[k]; #(BIT_NS);
            end
            uart_rx = 1; #(BIT_NS);
        end
    endtask

    task automatic send_break;
        begin
            // A low stop bit produces uart_framing_err, the packet-safe ABORT.
            uart_rx = 0; #(BIT_NS * 11);
            uart_rx = 1; #(BIT_NS * 3);
        end
    endtask

    initial begin : receiver
        reg [7:0] value;
        integer k;
        forever begin
            @(negedge uart_tx);
            #(BIT_NS / 2);
            if (!uart_tx) begin
                for (k = 0; k < 8; k = k + 1) begin
                    #(BIT_NS); value[k] = uart_tx;
                end
                #(BIT_NS);
                if (!uart_tx) begin
                    $display("packet UART TX framing error");
                    errors = errors + 1;
                end
                response[response_count] = value;
                response_count = response_count + 1;
            end
        end
    end

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

    task automatic send_frame(input [7:0] opcode, input integer length);
        reg [31:0] crc;
        begin
            crc = 32'hffffffff;
            send_byte(8'ha1); crc = crc_byte(crc, 8'ha1);
            send_byte(1); crc = crc_byte(crc, 1);
            send_byte(opcode); crc = crc_byte(crc, opcode);
            send_byte(0); crc = crc_byte(crc, 0);
            send_byte(length[7:0]); crc = crc_byte(crc, length[7:0]);
            send_byte(length[15:8]); crc = crc_byte(crc, length[15:8]);
            for (i = 0; i < length; i = i + 1) begin
                send_byte(payload[i]); crc = crc_byte(crc, payload[i]);
            end
            crc = ~crc;
            send_byte(crc[7:0]); send_byte(crc[15:8]);
            send_byte(crc[23:16]); send_byte(crc[31:24]);
        end
    endtask

    task automatic wait_response(input [7:0] status);
        integer total, length, guard;
        reg [31:0] crc;
        begin
            guard = 0;
            while (response_count < 5 && guard < 20000) begin
                #(BIT_NS); guard = guard + 1;
            end
            if (response_count < 5) begin
                $display("DEBUG rx_overrun=%0d rx_full=%0d core_ready=%0d tx_full=%0d frontend_busy=%0d rx_state=%0d tx_busy=%0d tx_start=%0d result_pending=%0d compute=%0d opcode=%02x len=%0d",
                         dut.rx_overrun, dut.rx_full, dut.core_rx_ready, dut.tx_full,
                         dut.g_packet.asic.packet_core.busy,
                         dut.g_packet.asic.packet_core.receiver.state,
                         dut.g_packet.asic.packet_core.tx_busy,
                         dut.g_packet.asic.packet_core.tx_start,
                         dut.g_packet.asic.packet_core.result_pending,
                         dut.g_packet.asic.packet_core.compute_state,
                         dut.g_packet.asic.packet_core.frame_opcode,
                         dut.g_packet.asic.packet_core.frame_length);
                $fatal(1, "packet response header timeout");
            end
            length = response[3] | response[4] << 8;
            total = 5 + length + 4;
            while (response_count < total && guard < 20000) begin
                #(BIT_NS); guard = guard + 1;
            end
            if (response_count != total) $fatal(1, "packet response length mismatch");
            if (response[0] !== 8'h5a || response[1] !== 1 || response[2] !== status)
                $fatal(1, "packet response status got=%02x expected=%02x", response[2], status);
            crc = 32'hffffffff;
            for (i = 0; i < total-4; i = i + 1) crc = crc_byte(crc, response[i]);
            crc = ~crc;
            if ({response[total-1],response[total-2],response[total-3],response[total-4]} !== crc)
                $fatal(1, "packet response CRC mismatch");
        end
    endtask

    task automatic clear_response;
        begin
            response_count = 0;
            for (i = 0; i < 256; i = i + 1) response[i] = 0;
        end
    endtask

    reg [31:0] result_crc;
    integer result_length;

    initial begin
        #(BIT_NS * 5);

        // NEGOTIATE interpreter-compatible profile.
        clear_payload(); clear_response();
        payload[0] = 1; payload[1] = 1; payload[2] = 1;
        send_frame(8'h10, 7); wait_response(8'h00);
        if (response[11] !== 6 || response[15] !== 8'h31)
            $fatal(1, "packet NEGOTIATE capabilities mismatch");

        // STATUS is packetized and non-mutating.
        clear_payload(); clear_response();
        send_frame(8'h13, 0); wait_response(8'h03);
        if (response[3] !== 20 || response[5] !== 0)
            $fatal(1, "packet STATUS schema mismatch");

        // SET carries 0x7f as ordinary payload data; it must not become ABORT.
        clear_payload(); clear_response();
        put_u32(0, 32'h1234); put_u32(4, 0); put_u32(8, 0);
        payload[12] = 1; put_u32(14, 7); payload[18] = 8'h7f;
        payload[34] = 0;
        send_frame(8'h03, 51); wait_response(8'h00);
        if (response[17] !== 1 || response[22] !== 8'h7f)
            $fatal(1, "packet SET result mismatch");
        result_length = response[3] | response[4] << 8;
        result_crc = 32'hffffffff;
        for (i = 0; i < result_length; i = i + 1)
            result_crc = crc_byte(result_crc, response[5+i]);
        result_crc = ~result_crc;

        clear_payload(); clear_response();
        put_u32(0, 32'h1234); put_u32(4, result_crc);
        send_frame(8'h12, 8); wait_response(8'h02);

        // Unknown opcode is framed as BAD_OPCODE and the lane remains reusable.
        clear_payload(); clear_response();
        send_frame(8'h7f, 0); wait_response(8'h82);

        // UART BREAK aborts a partial frame without emitting a response.
        #(BIT_NS * 2); // let the response stop bit finish before resetting capture
        clear_response();
        send_byte(8'ha1); send_byte(1); send_byte(8'h03);
        send_break(); #(BIT_NS * 20);
        if (response_count != 0) begin
            $display("DEBUG abort response_count=%0d bytes=%02x %02x %02x",
                     response_count, response[0], response[1], response[2]);
            $fatal(1, "ABORT emitted an unintended response");
        end
        clear_payload();
        send_frame(8'h13, 0); wait_response(8'h03);

        if (dut.rx_overrun) $fatal(1, "packet UART bridge overran RX buffer");
        $display("PASS: packetized LSC-1 UART bridge");
        $finish;
    end

    initial begin
        #100_000_000;
        $fatal(1, "packet UART bridge global timeout");
    end
endmodule

`default_nettype wire

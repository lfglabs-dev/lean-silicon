`timescale 1ns/1ps
`default_nettype none

// One-frame harness used by the Python RTL differential test.  Input is a
// temporary readmemh file; output is one machine-readable RESPONSE line.
module tb_lsc1_packet_vector;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, abort = 0;
    reg [7:0] rx_data = 0;
    reg rx_valid = 0;
    wire rx_ready;
    wire [7:0] tx_data;
    wire tx_valid;
    reg tx_ready = 0;
    wire busy, fault, done_pulse;

    reg [7:0] request [0:511];
    reg [7:0] response [0:511];
    integer request_length, response_count = 0, total = 0;
    integer request2_length = 0, request3_length = 0, request4_length = 0;
    integer request5_length = 0, request6_length = 0, request7_length = 0;
    integer cycle = 0, i;
    integer trace_rx_blocked = 0, trace_tx_blocked = 0, trace_done = 0;
    reg [31:0] initial_service_seq;
    reg [1023:0] request_path, request2_path, request3_path, request4_path;
    reg [1023:0] request5_path, request6_path, request7_path;

    lsc1_packet_frontend dut (
        .clk(clk), .rst_n(rst_n), .abort(abort),
        .rx_data(rx_data), .rx_valid(rx_valid), .rx_ready(rx_ready),
        .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(tx_ready),
        .busy(busy), .fault(fault), .done_pulse(done_pulse)
    );

    always @(negedge clk) begin
        cycle = cycle + 1;
        tx_ready = (cycle % 5) != 0;
    end

    always @(posedge clk) begin
        if (rst_n && rx_valid && !rx_ready) trace_rx_blocked = trace_rx_blocked + 1;
        if (rst_n && tx_valid && !tx_ready) trace_tx_blocked = trace_tx_blocked + 1;
        if (rst_n && done_pulse) trace_done = trace_done + 1;
        if (tx_valid && tx_ready) begin
            response[response_count] <= tx_data;
            response_count <= response_count + 1;
            if (response_count == 4)
                total <= 9 + response[3] + (tx_data << 8);
        end
    end

    task automatic send_byte(input [7:0] value, input integer gap);
        begin
            repeat (gap) @(posedge clk);
            @(negedge clk); rx_data = value; rx_valid = 1;
            do @(posedge clk); while (!rx_ready);
            @(negedge clk); rx_valid = 0;
        end
    endtask

    task automatic run_request(input [1023:0] path, input integer length);
        begin
            $readmemh(path, request);
            response_count = 0; total = 0;
            for (i = 0; i < length; i = i + 1)
                send_byte(request[i], i % 3);
            if ($test$plusargs("INJECT_RX_STALL")) begin
                wait (!rx_ready);
                @(negedge clk); rx_valid = 1;
                @(posedge clk);
                @(negedge clk); rx_valid = 0;
            end
            wait (total != 0 && response_count == total);
            $write("RESPONSE ");
            for (i = 0; i < total; i = i + 1)
                $write("%02x", response[i]);
            $write("\n");
        end
    endtask

    initial begin
        if (!$value$plusargs("REQUEST=%s", request_path) ||
            !$value$plusargs("LENGTH=%d", request_length))
            $fatal(1, "REQUEST and LENGTH plusargs are required");
        repeat (4) @(posedge clk);
        rst_n = 1;
        repeat (2) @(posedge clk);
        if ($test$plusargs("TRACE_IDLE_RX_BLOCKED") ||
            $test$plusargs("TRACE_VALID_RX_BLOCKED")) begin
            @(negedge clk);
            force rx_ready = 0;
            rx_valid = $test$plusargs("TRACE_VALID_RX_BLOCKED");
            @(posedge clk);
            @(negedge clk);
            release rx_ready;
            rx_valid = 0;
            $display("RTL_COUNTS rx_blocked=%0d tx_blocked=%0d done=%0d",
                     trace_rx_blocked, trace_tx_blocked, trace_done);
            $finish;
        end
        if ($value$plusargs("SERVICE_SEQ=%h", initial_service_seq))
            dut.service_seq = initial_service_seq;
        run_request(request_path, request_length);
        if ($test$plusargs("ABORT_AFTER_FIRST")) begin
            $display("RTL_CONTROL ABORT BEFORE result=%0d service=%0d tx=%0d",
                     dut.result_pending, dut.service_pending, tx_valid);
            @(negedge clk); abort = 1;
            @(posedge clk);
            @(negedge clk); abort = 0;
            #1 $display("RTL_CONTROL ABORT AFTER result=%0d service=%0d tx=%0d",
                        dut.result_pending, dut.service_pending, tx_valid);
        end
        if ($test$plusargs("RESET_AFTER_FIRST")) begin
            $display("RTL_CONTROL RESET BEFORE result=%0d service=%0d tx=%0d",
                     dut.result_pending, dut.service_pending, tx_valid);
            @(negedge clk); rst_n = 0;
            repeat (2) @(posedge clk);
            @(negedge clk); rst_n = 1;
            #1 $display("RTL_CONTROL RESET AFTER result=%0d service=%0d tx=%0d",
                        dut.result_pending, dut.service_pending, tx_valid);
        end
        if ($value$plusargs("REQUEST2=%s", request2_path) &&
            $value$plusargs("LENGTH2=%d", request2_length)) run_request(request2_path, request2_length);
        if ($value$plusargs("REQUEST3=%s", request3_path) &&
            $value$plusargs("LENGTH3=%d", request3_length)) run_request(request3_path, request3_length);
        if ($value$plusargs("REQUEST4=%s", request4_path) &&
            $value$plusargs("LENGTH4=%d", request4_length)) run_request(request4_path, request4_length);
        if ($value$plusargs("REQUEST5=%s", request5_path) &&
            $value$plusargs("LENGTH5=%d", request5_length)) run_request(request5_path, request5_length);
        if ($value$plusargs("REQUEST6=%s", request6_path) &&
            $value$plusargs("LENGTH6=%d", request6_length)) run_request(request6_path, request6_length);
        if ($value$plusargs("REQUEST7=%s", request7_path) &&
            $value$plusargs("LENGTH7=%d", request7_length)) run_request(request7_path, request7_length);
        $display("RTL_COUNTS rx_blocked=%0d tx_blocked=%0d done=%0d",
                 trace_rx_blocked, trace_tx_blocked, trace_done);
        $finish;
    end

    initial begin
        #20_000_000;
        $fatal(1, "vector differential timeout");
    end
endmodule

`default_nettype wire

`timescale 1ns/1ps
module tb_scalar_retire_trace;
    reg clk = 0, rst_n = 0, abort = 0, rx_valid = 0, tx_ready = 1;
    reg [7:0] rx_data = 0;
    wire rx_ready, tx_valid, busy, fault, done_pulse;
    wire [7:0] tx_data;
    integer cycle = 0, tx_count, done_count, accept_cycle, result_last_cycle;
    integer retire_accept_cycle, done_cycle, i, request_length, response_length;
    reg [831:0] request_bits;
    reg [447:0] response_bits;
    reg [143:0] retire_bits;
    reg [8*8-1:0] case_name;

    lsc1_packet_frontend dut(.*);
    always #5 clk = ~clk;
    always @(posedge clk) begin
        if (!rst_n) cycle <= 0;
        else cycle <= cycle + 1;
        if (!rst_n) begin
            tx_count <= 0; done_count <= 0; accept_cycle <= 0;
            result_last_cycle <= 0; retire_accept_cycle <= 0; done_cycle <= 0;
        end else if (tx_valid && tx_ready) begin
            if (tx_count < response_length &&
                tx_data !== response_bits[(response_length-1-tx_count)*8 +: 8])
                $fatal(1, "%s RESULT byte %0d got=%02x expected=%02x", case_name,
                    tx_count, tx_data, response_bits[(response_length-1-tx_count)*8 +: 8]);
            tx_count <= tx_count + 1;
            if (tx_count == response_length-1) result_last_cycle <= cycle;
        end
        if (rst_n && done_pulse) begin
            done_count <= done_count + 1;
            if (done_cycle == 0) done_cycle <= cycle;
        end
        if (rst_n && dut.frame_valid && dut.event_ready) begin
            if (accept_cycle == 0) accept_cycle <= cycle;
            else if (retire_accept_cycle == 0) retire_accept_cycle <= cycle;
        end
    end

    task send_byte(input [7:0] value);
        begin
            rx_data = value; rx_valid = 1;
            do @(posedge clk); while (!rx_ready);
            #1 rx_valid = 0;
        end
    endtask

    task run_case;
        begin
            rst_n = 0; rx_valid = 0; repeat (2) @(posedge clk); @(negedge clk); rst_n = 1;
            for (i=0; i<request_length; i=i+1)
                send_byte(request_bits[(request_length-1-i)*8 +: 8]);
            wait (tx_count == response_length); @(posedge clk); #1;
            for (i=0; i<18; i=i+1)
                send_byte(retire_bits[(17-i)*8 +: 8]);
            wait(done_pulse); #1;
            if (dut.retire_seq !== 1 || dut.committed_pc !== 1 ||
                dut.committed_fp !== 0 || dut.result_pending !== 0)
                $fatal(1, "%s commit mismatch", case_name);
            repeat (2) @(posedge clk);
            if (done_count !== 1) $fatal(1, "%s done count %0d", case_name, done_count);
            $display("%s_LIFECYCLE accept=%0d result_last=%0d retire_accept=%0d done=%0d bytes=%0d",
                case_name, accept_cycle, result_last_cycle, retire_accept_cycle, done_cycle, response_length);
        end
    endtask

    initial begin
        case_name="SET"; request_length=61; response_length=48;
        request_bits=488'ha101030033000100000000000000000000000100030000002a0000000000000000000000000000000000000000000000000000000000000000a817d891;
        response_bits=384'h5a0100270001000000010000000000000001030000002a000000000000000000000000000000000103000000ce0e6532;
        retire_bits=144'ha1011200080001000000e5e567ad7364382c; run_case();
        case_name="XOR"; request_length=87; response_length=56;
        request_bits=696'ha10101004d000100000000000000000000000100010000000200000003000000011200000000000000000000000000000001340000000000000000000000000000000000000000000000000000000000000000dbc3b18e;
        response_bits=448'h5a01002f00010000000100000000000000010300000026000000000000000000000000000000000301000000020000000300000046f80c6d;
        retire_bits=144'ha10112000800010000007f08ce772a1a3c46; run_case();
        case_name="MUL"; request_length=104; response_length=56;
        request_bits=832'ha10102005e00010000000000000000000000010001000000020000000300000001120000000000000000000000000000000101000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000009f22a3b7;
        response_bits=448'h5a01002f0001000000010000000000000001030000001200000000000000000000000000000000030100000002000000030000006030bb0d;
        retire_bits=144'ha101120008000100000059c079171774efba; run_case();
        $display("SCALAR_RETIRE_TRACE_PASS"); $finish;
    end
    initial begin repeat (20000) @(posedge clk); $fatal(1,"timeout"); end
endmodule

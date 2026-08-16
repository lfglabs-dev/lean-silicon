`timescale 1ns/1ps
`default_nettype none

module tb_blake3_retire_commit;
    reg clk = 0, rst_n = 0, abort = 0, rx_valid = 0, tx_ready = 1;
    reg [7:0] rx_data = 0;
    wire rx_ready, tx_valid, busy, fault, done_pulse;
    wire [7:0] tx_data;
    integer cycle = 0, done_count = 0, response_count = 0;
    integer retire_accept_cycle = 0, commit_cycle = 0, done_cycle = 0;
    integer input_length, expected_length, i;
    reg [1599:0] input_bits;
    reg [1047:0] expected_bits;
    reg retire_accepted;

    lsc1_packet_frontend dut(.*);
    always #5 clk = ~clk;

    always @(posedge clk) begin
        if (!rst_n) begin
            cycle <= 0;
            done_count <= 0;
            retire_accept_cycle <= 0;
            commit_cycle <= 0;
            done_cycle <= 0;
        end else begin
            cycle <= cycle + 1;
            if (done_pulse) begin
                done_count <= done_count + 1;
                if (done_cycle == 0) done_cycle <= cycle;
            end
        end
        if (tx_valid && tx_ready) begin
            if (tx_data !== expected_bits[(expected_length-1-response_count)*8 +: 8])
                $fatal(1, "response byte %0d got=%02x expected=%02x",
                       response_count, tx_data,
                       expected_bits[(expected_length-1-response_count)*8 +: 8]);
            response_count <= response_count + 1;
        end

`ifdef PRE_EXTRACTION
        retire_accepted = rst_n && dut.frame_valid && dut.event_ready &&
                          dut.frame_opcode == 8'h12 && dut.frame_length == 8 &&
                          dut.result_pending &&
                          dut.frame_payload[0 +: 32] == dut.staged_txn_id &&
                          dut.frame_payload[32 +: 32] == dut.staged_result_crc;
`else
        retire_accepted = rst_n && dut.frame_valid && dut.event_ready &&
                          dut.frame_opcode == 8'h12 && dut.frame_length == 8 &&
                          dut.blake_result_pending && dut.blake_retire_match;
`endif
        if (retire_accepted) begin
            retire_accept_cycle = cycle;
            #1;
            if (!done_pulse)
                $fatal(1, "BLAKE3 DONE not aligned with accepted RETIRE commit edge");
            if (dut.committed_pc !== 32'd3 || dut.committed_fp !== 32'd64 ||
                !dut.state_valid || dut.retire_seq !== 1 ||
`ifdef PRE_EXTRACTION
                dut.result_pending)
`else
                dut.blake_result_pending || dut.blake3_lifecycle.retire_seq !== 1)
`endif
                $fatal(1, "BLAKE3 architectural/lifecycle commit not atomic with RETIRE acceptance");
            commit_cycle = retire_accept_cycle;
        end
    end

    task send_input;
        begin
            for (i = 0; i < input_length; i = i + 1) begin
                @(negedge clk);
                rx_data = input_bits[(input_length-1-i)*8 +: 8];
                rx_valid = 1;
                do @(posedge clk); while (!rx_ready);
                @(negedge clk);
                rx_valid = 0;
            end
        end
    endtask

    task wait_response;
        integer guard;
        begin
            guard = 0;
            while (response_count != expected_length) begin
                @(posedge clk); guard = guard + 1;
                if (guard > 5000) $fatal(1, "response timeout");
            end
            @(negedge clk);
            response_count = 0;
        end
    endtask

    initial begin
        repeat (2) @(posedge clk); @(negedge clk); rst_n = 1;

        input_length = 200;
        input_bits = 1600'ha1010800be00403020100200000040000000010000000000010000000200000003000000080000000a00000000000000000000004000000000000000010b00000000000000000000000000000001160000000000000000000000000000000121000000000000000000000000000000012c0000000000000000000000000000000137000000000000000000000000000000014200000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000b773dba1;
        expected_length = 131;
        expected_bits = 1048'h5a01017a00403020100100000001000b00000000000000000000000000000016000000000000000000000000000000210000000000000000000000000000002c000000000000000000000000000000370000000000000000000000000000004200000000000000000000000000000000000000000000004000000000000000bdd58dd8;
        send_input(); wait_response();

        input_length = 52;
        input_bits = 416'ha10111002a0040302010010000000100f0b6a5ddd1b58f91536c77f8a3b3918eee3b6dc8a4501dc645da803a3b397207de89fdac;
        expected_length = 96;
        expected_bits = 768'h5a01005700403020100300000040000000024a000000f0b6a5ddd1b58f91536c77f8a3b3918e4b000000ee3b6dc8a4501dc645da803a3b39720700084000000041000000420000004300000048000000490000004a0000004b0000004fe2e8d0;
        send_input(); wait_response();

        input_length = 18;
        input_bits = 144'ha10112000800403020109c96789dcb9623ad;
        expected_length = 25;
        expected_bits = 200'h5a0102100040302010010000000300000040000000aa69c315;
        send_input(); wait_response();
        repeat (3) @(posedge clk); #1;

        if (retire_accept_cycle == 0 || commit_cycle != retire_accept_cycle)
            $fatal(1, "matching RETIRE was not observed and committed");
        if (done_count !== 1)
            $fatal(1, "BLAKE3 DONE count got=%0d expected=1", done_count);
        if (done_cycle !== retire_accept_cycle + 1)
            $fatal(1, "sampled DONE cycle %0d does not follow accept/commit cycle %0d",
                   done_cycle, retire_accept_cycle);
        $display("BLAKE3_RETIRE_COMMIT_PASS accept=%0d done_sample=%0d",
                 retire_accept_cycle, done_cycle);
        $finish;
    end

    initial begin repeat (30000) @(posedge clk); $fatal(1, "timeout"); end
endmodule

`default_nettype wire

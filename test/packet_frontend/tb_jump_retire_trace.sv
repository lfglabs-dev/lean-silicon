`timescale 1ns/1ps
module tb_jump_retire_trace;
    reg clk = 0, rst_n = 0, abort = 0, rx_valid = 0, tx_ready = 1;
    reg [7:0] rx_data = 0;
    wire rx_ready, tx_valid, busy, fault, done_pulse;
    wire [7:0] tx_data;
    integer cycle = 0, i, tx_count = 0, done_count = 0;
    integer accept_cycle = 0, result_last_cycle = 0;
    integer retire_accept_cycle = 0, done_cycle = 0;
    reg [7:0] request [0:112];
    reg [7:0] retire [0:17];

    lsc1_packet_frontend dut(.*);
    always #5 clk = ~clk;
    always @(posedge clk) begin
        cycle <= cycle + 1;
        if (tx_valid && tx_ready) begin
            tx_count <= tx_count + 1;
            if (tx_count == 35) result_last_cycle <= cycle;
        end
        if (done_pulse) begin
            done_count <= done_count + 1;
            if (done_cycle == 0) done_cycle <= cycle;
        end
        if (dut.frame_valid && dut.event_ready) begin
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

    initial begin
        for (i = 0; i < 113; i = i + 1) request[i] = 0;
        request[0]=8'ha1; request[1]=1; request[2]=7; request[4]=8'h67;
        request[6]=1; request[18]=1; request[24]=1; request[28]=2;
        request[32]=1; request[33]=1; request[49]=1; request[50]=2;
        request[66]=1; request[67]=4; request[83]=1; request[84]=1;
        request[88]=2; request[92]=1; request[93]=1;
        request[109]=8'hf3; request[110]=8'he4; request[111]=8'he5; request[112]=8'h3f;
        for (i = 0; i < 18; i = i + 1) retire[i] = 0;
        retire[0]=8'ha1; retire[1]=1; retire[2]=8'h12; retire[4]=8'h08;
        retire[6]=1; retire[10]=8'h0c; retire[11]=8'h01; retire[12]=8'h58; retire[13]=8'h40;
        retire[14]=8'h44; retire[15]=8'ha6; retire[16]=8'hc1; retire[17]=8'haf;
        @(posedge clk); @(negedge clk); rst_n = 1;
        for (i = 0; i < 113; i = i + 1) send_byte(request[i]);
        wait (tx_count == 36); @(posedge clk); #1;
        if (dut.staged_result_crc !== 32'h4058010c) $fatal(1, "result CRC mismatch got=%08x", dut.staged_result_crc);
        for (i = 0; i < 18; i = i + 1) send_byte(retire[i]);
        wait (done_pulse); #1;
        if (dut.retire_seq !== 1 || dut.committed_pc !== 1 ||
            dut.committed_fp !== 2 || dut.result_pending !== 0)
            $fatal(1, "commit mismatch");
        repeat (3) @(posedge clk);
        if (done_count !== 1) $fatal(1, "done count %0d", done_count);
        $display("JUMP_RETIRE_FIRST_DONE_CYCLE=%0d", done_cycle);
        $display("JUMP_LIFECYCLE_CYCLES accept=%0d result_last=%0d retire_accept=%0d", accept_cycle, result_last_cycle, retire_accept_cycle);
        $display("JUMP_RETIRE_TRACE_PASS result_envelope_bytes=36 done_count=%0d", done_count);
        $finish;
    end
    initial begin
        repeat (10000) @(posedge clk);
        $fatal(1, "timeout cycle=%0d tx=%0d", cycle, tx_count);
    end
endmodule

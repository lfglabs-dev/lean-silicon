`timescale 1ns/1ps
module tb_deref_retire_trace;
    reg clk = 0, rst_n = 0, abort = 0, rx_valid = 0, tx_ready = 1;
    reg [7:0] rx_data = 0;
    wire rx_ready, tx_valid, busy, fault, done_pulse;
    wire [7:0] tx_data;
    integer cycle = 0, i, tx_count = 0, done_count = 0;
    integer accept_cycle = 0, done_cycle = 0;
    reg [7:0] request [0:90];
    reg [7:0] retire [0:17];

    lsc1_packet_frontend dut(.*);
    always #5 clk = ~clk;
    always @(posedge clk) begin
        cycle <= cycle + 1;
        if (tx_valid && tx_ready) tx_count <= tx_count + 1;
        if (done_pulse) begin
            done_count <= done_count + 1;
            if (done_cycle == 0) done_cycle <= cycle;
        end
        if (dut.frame_valid && dut.event_ready && accept_cycle == 0)
            accept_cycle <= cycle;
    end

    task send_byte(input [7:0] value);
        begin
            rx_data = value; rx_valid = 1;
            do @(posedge clk); while (!rx_ready);
            #1 rx_valid = 0;
        end
    endtask

    initial begin
        for (i = 0; i < 91; i = i + 1) request[i] = 0;
        request[0]=8'ha1; request[1]=1; request[2]=4; request[4]=8'h51;
        request[6]=1; request[14]=1; request[18]=1; request[24]=1;
        request[24]=2; request[28]=2; request[32]=1; request[33]=1;
        request[87]=8'ha9; request[88]=8'h7f;
        request[89]=8'hb6; request[90]=8'h92;
        for (i = 0; i < 18; i = i + 1) retire[i] = 0;
        retire[0]=8'ha1; retire[1]=1; retire[2]=8'h12; retire[4]=8'h08;
        // CRC-32 of the 35 bytes emitted by this concrete RESULT.
        retire[6]=1;
        retire[10]=8'h64; retire[11]=8'h05; retire[12]=8'h84; retire[13]=8'h70;
        retire[14]=8'hcb; retire[15]=8'h6b; retire[16]=8'h0e; retire[17]=8'h5d;
        // Match the formal startup contract without racing DUT sampling: one
        // complete rising edge in reset, then release on the falling edge.
        @(posedge clk); @(negedge clk); rst_n = 1;
        for (i = 0; i < 91; i = i + 1) send_byte(request[i]);
        wait (tx_count == 44); @(posedge clk); #1;
        if (dut.staged_result_crc !== 32'h70840564) $fatal(1, "result CRC mismatch got=%08x", dut.staged_result_crc);
        for (i = 0; i < 18; i = i + 1) send_byte(retire[i]);
        wait (done_pulse); #1;
        if (dut.retire_seq !== 1 || dut.committed_pc !== 1 ||
            dut.committed_fp !== 1 || dut.result_pending !== 0)
            $fatal(1, "commit mismatch");
        repeat (3) @(posedge clk);
        if (done_count !== 1) $fatal(1, "done count %0d", done_count);
        if (accept_cycle !== 92 || done_cycle !== 2784)
            $fatal(1, "witness timing changed accept=%0d done=%0d", accept_cycle, done_cycle);
        $display("DEREF_RETIRE_FIRST_DONE_CYCLE=%0d", done_cycle);
        $display("DEREF_RETIRE_TRACE_PASS accept_cycle=%0d result_envelope_bytes=44 done_count=%0d", accept_cycle, done_count);
        $finish;
    end
    initial begin
        repeat (10000) @(posedge clk);
        $fatal(1, "timeout cycle=%0d tx=%0d", cycle, tx_count);
    end
endmodule

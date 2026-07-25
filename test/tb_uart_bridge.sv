`timescale 1ns/1ps
`default_nettype none
/*
 * Self-checking testbench for the UART bridge and the exact lean_silicon_lsc1
 * pin boundary.
 *
 * The bench contains a real 1 Mbaud 8N1 receiver rather than an activity
 * counter, so three failure modes that a liveness window cannot see are fatal
 * here: a response byte the bridge never serialises, a byte whose final data
 * bit is not held for a full baud interval, and a response that does not match
 * the independently computed expected value.
 */
module tb_uart_bridge;

    localparam integer CLK_HALF_NS = 20;   // 25 MHz
    localparam integer BIT_NS      = 1000; // 1 Mbaud
    localparam integer MAX_BYTES   = 64;

    reg clk = 1'b0;
    always #(CLK_HALF_NS) clk = ~clk;

    reg  uart_rx = 1'b1;
    wire uart_tx;

    uart_bridge dut (
        .clk(clk),
        .uart_rx(uart_rx),
        .uart_tx(uart_tx)
    );

    integer errors = 0;

    // ---------------------------------------------------------------- host TX
    task automatic send_byte(input [7:0] b);
        integer i;
        begin
            uart_rx = 1'b0;
            #(BIT_NS);
            for (i = 0; i < 8; i = i + 1) begin
                uart_rx = b[i];
                #(BIT_NS);
            end
            uart_rx = 1'b1;
            #(BIT_NS);
        end
    endtask

    // ------------------------------------------------- host RX (real receiver)
    reg [7:0] rx_bytes [0:MAX_BYTES-1];
    integer   rx_count       = 0;
    integer   rx_frame_error = 0;

    initial begin : uart_receiver
        reg [7:0] b;
        integer   i;
        forever begin
            @(negedge uart_tx);
            #(BIT_NS / 2);
            if (uart_tx === 1'b0) begin
                for (i = 0; i < 8; i = i + 1) begin
                    #(BIT_NS);
                    b[i] = uart_tx;
                end
                #(BIT_NS);
                if (uart_tx !== 1'b1) begin
                    rx_frame_error = rx_frame_error + 1;
                    $display("FAIL stop bit not high after byte %02h", b);
                end
                if (rx_count < MAX_BYTES) rx_bytes[rx_count] = b;
                rx_count = rx_count + 1;
            end
        end
    end

    // ------------------------------------------------------------- expectation
    reg [7:0] exp_bytes [0:MAX_BYTES-1];
    integer   exp_count = 0;

    task automatic expect_reset;
        begin
            rx_count  = 0;
            exp_count = 0;
        end
    endtask

    task automatic expect_byte(input [7:0] b);
        begin
            exp_bytes[exp_count] = b;
            exp_count = exp_count + 1;
        end
    endtask

    // Waits for the expected number of bytes, then settles to catch extras.
    task automatic check_response(input [8*24-1:0] label);
        integer waited;
        integer i;
        integer limit;
        begin
            // Generous budget: every response in this bench is <= 16 bytes.
            limit  = 40 * (exp_count + 4);
            waited = 0;
            while (rx_count < exp_count && waited < limit) begin
                #(BIT_NS);
                waited = waited + 1;
            end

            if (rx_count < exp_count) begin
                $display("FAIL %0s: missing TX, expected %0d byte(s), received %0d",
                         label, exp_count, rx_count);
                errors = errors + 1;
            end else begin
                // Settle so a spurious extra byte is observed rather than missed.
                #(BIT_NS * 14);
                if (rx_count != exp_count) begin
                    $display("FAIL %0s: expected %0d byte(s), received %0d",
                             label, exp_count, rx_count);
                    errors = errors + 1;
                end
            end

            for (i = 0; i < exp_count; i = i + 1) begin
                if (i < rx_count && rx_bytes[i] !== exp_bytes[i]) begin
                    $display("FAIL %0s: byte %0d is %02h, expected %02h",
                             label, i, rx_bytes[i], exp_bytes[i]);
                    errors = errors + 1;
                end
            end

            if (dut.rx_overrun !== 1'b0) begin
                $display("FAIL %0s: bridge reported a receive overrun", label);
                errors = errors + 1;
            end
        end
    endtask

    // --------------------------------------------------------------- vectors
    // MUL operands and the product, computed independently by sim/model.py
    // (schoolbook carry-less product plus long reduction, cross-checked against
    // the LSB-first bit-serial model) over GF(2^128) / x^128 + x^7 + x^2 + x + 1.
    reg [7:0] mul_a   [0:15];
    reg [7:0] mul_b   [0:15];
    reg [7:0] mul_exp [0:15];

    task automatic load_mul_vector;
        begin
            mul_a[0]=8'h11; mul_a[1]=8'h22; mul_a[2]=8'h33; mul_a[3]=8'h44;
            mul_a[4]=8'h55; mul_a[5]=8'h66; mul_a[6]=8'h77; mul_a[7]=8'h88;
            mul_a[8]=8'h99; mul_a[9]=8'haa; mul_a[10]=8'hbb; mul_a[11]=8'hcc;
            mul_a[12]=8'hdd; mul_a[13]=8'hee; mul_a[14]=8'hff; mul_a[15]=8'h01;

            mul_b[0]=8'h02; mul_b[1]=8'h00; mul_b[2]=8'h00; mul_b[3]=8'h00;
            mul_b[4]=8'h00; mul_b[5]=8'h00; mul_b[6]=8'h00; mul_b[7]=8'h00;
            mul_b[8]=8'h00; mul_b[9]=8'h00; mul_b[10]=8'h00; mul_b[11]=8'h00;
            mul_b[12]=8'h00; mul_b[13]=8'h00; mul_b[14]=8'h00; mul_b[15]=8'h00;

            mul_exp[0]=8'h22; mul_exp[1]=8'h44; mul_exp[2]=8'h66; mul_exp[3]=8'h88;
            mul_exp[4]=8'haa; mul_exp[5]=8'hcc; mul_exp[6]=8'hee; mul_exp[7]=8'h10;
            mul_exp[8]=8'h33; mul_exp[9]=8'h55; mul_exp[10]=8'h77; mul_exp[11]=8'h99;
            mul_exp[12]=8'hbb; mul_exp[13]=8'hdd; mul_exp[14]=8'hff; mul_exp[15]=8'h03;
        end
    endtask

    integer i;
    reg [7:0] set_payload [0:15];
    reg [7:0] xor_a [0:15];
    reg [7:0] xor_b [0:15];

    initial begin
        $display("tb_uart_bridge start");
        load_mul_vector;
        #(BIT_NS * 4);

        // ---- STATUS: exactly four bytes must reach the host ----------------
        expect_reset;
        send_byte(8'h7e);
        expect_byte(8'h01);
        expect_byte(8'h01);
        expect_byte(8'h0f);
        expect_byte(8'h08);
        check_response("STATUS");

        // ---- SET128 with an all-zero payload -------------------------------
        // Every echoed byte has bit 7 clear, so a final data bit that is not
        // held for a full baud interval is received as 80 instead of 00.
        expect_reset;
        send_byte(8'h03);
        for (i = 0; i < 16; i = i + 1) begin
            set_payload[i] = 8'h00;
            send_byte(set_payload[i]);
        end
        for (i = 0; i < 16; i = i + 1) expect_byte(set_payload[i]);
        check_response("SET zero");

        // ---- SET128 with a mixed payload -----------------------------------
        expect_reset;
        send_byte(8'h03);
        for (i = 0; i < 16; i = i + 1) begin
            set_payload[i] = i[7:0] ^ 8'h5a;
            send_byte(set_payload[i]);
        end
        for (i = 0; i < 16; i = i + 1) expect_byte(set_payload[i]);
        check_response("SET mixed");

        // ---- XOR128 ---------------------------------------------------------
        expect_reset;
        send_byte(8'h01);
        for (i = 0; i < 16; i = i + 1) begin
            xor_a[i] = 8'ha5 + i[7:0];
            xor_b[i] = 8'h3c ^ i[7:0];
            send_byte(xor_a[i]);
            send_byte(xor_b[i]);
        end
        for (i = 0; i < 16; i = i + 1) expect_byte(xor_a[i] ^ xor_b[i]);
        check_response("XOR");

        // ---- MUL128 against the independent oracle vector -------------------
        expect_reset;
        send_byte(8'h02);
        for (i = 0; i < 16; i = i + 1) send_byte(mul_a[i]);
        for (i = 0; i < 16; i = i + 1) send_byte(mul_b[i]);
        for (i = 0; i < 16; i = i + 1) expect_byte(mul_exp[i]);
        check_response("MUL");

        // ---- Unknown opcode must report a protocol fault, not silence -------
        expect_reset;
        send_byte(8'hff);
        expect_byte(8'he0);
        check_response("BAD OPCODE");

        // ---- Abort recovery: 0x7f mid-command, then STATUS still answers ----
        expect_reset;
        send_byte(8'h03);
        send_byte(8'h7f);
        #(BIT_NS * 20);
        expect_reset;
        send_byte(8'h7e);
        expect_byte(8'h01);
        expect_byte(8'h01);
        expect_byte(8'h0f);
        expect_byte(8'h08);
        check_response("STATUS after abort");

        if (rx_frame_error != 0) begin
            $display("FAIL %0d framing error(s) on the bridge transmit line",
                     rx_frame_error);
            errors = errors + 1;
        end

        if (errors != 0) begin
            $display("tb_uart_bridge FAILED with %0d error(s)", errors);
            $fatal(1, "tb_uart_bridge failed");
        end

        $display("tb_uart_bridge PASSED");
        $finish;
    end

    // Hard stop so a bridge that never transmits cannot hang the suite.
    initial begin
        #20_000_000;
        $display("FAIL tb_uart_bridge global timeout");
        $fatal(1, "tb_uart_bridge timeout");
    end

endmodule
`default_nettype wire

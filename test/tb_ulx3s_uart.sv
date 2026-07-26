`timescale 1ns/1ps
`default_nettype none
module tb_ulx3s_uart;
    localparam integer CLKS_PER_BIT = 217;
    reg clk = 1'b0;
    reg host_tx = 1'b1;
    wire host_rx;
    wire [7:0] led;
    reg [7:0] got;
    reg [7:0] expected;
    integer i;
    always #20 clk = !clk;

    ulx3s_lsc1_top dut (
        .clk_25mhz(clk), .ftdi_txd(host_tx), .ftdi_rxd(host_rx), .led(led)
    );

    task send_byte(input [7:0] value);
        integer bit_number;
        begin
            host_tx = 1'b0;
            repeat (CLKS_PER_BIT) @(posedge clk);
            for (bit_number = 0; bit_number < 8; bit_number = bit_number + 1) begin
                host_tx = value[bit_number];
                repeat (CLKS_PER_BIT) @(posedge clk);
            end
            host_tx = 1'b1;
            repeat (CLKS_PER_BIT) @(posedge clk);
        end
    endtask

    task receive_byte(output [7:0] value);
        integer bit_number;
        begin
            @(negedge host_rx);
            repeat (CLKS_PER_BIT + (CLKS_PER_BIT / 2)) @(posedge clk);
            for (bit_number = 0; bit_number < 8; bit_number = bit_number + 1) begin
                value[bit_number] = host_rx;
                repeat (CLKS_PER_BIT) @(posedge clk);
            end
            if (!host_rx) begin
                $display("FAIL: UART stop bit low");
                $fatal(1);
            end
        end
    endtask

    task check_byte(input [7:0] actual, input [7:0] wanted);
        begin
            if (actual !== wanted) begin
                $display("FAIL: got %02x expected %02x", actual, wanted);
                $fatal(1);
            end
        end
    endtask

    initial begin
        wait (led[0]);
        repeat (32) @(posedge clk);

        fork
            send_byte(8'h7e);
            begin receive_byte(got); check_byte(got, 8'h01); end
        join
        receive_byte(got); check_byte(got, 8'h01);
        receive_byte(got); check_byte(got, 8'h0f);
        receive_byte(got); check_byte(got, 8'h08);

        send_byte(8'h03);
        for (i = 0; i < 16; i = i + 1) begin
            expected = i[7:0];
            fork
                send_byte(expected);
                begin receive_byte(got); check_byte(got, expected); end
            join
        end

        send_byte(8'h01);
        for (i = 0; i < 16; i = i + 1) begin
            send_byte(i[7:0]);
            expected = 8'hf0 + i[7:0];
            fork
                send_byte(expected);
                begin receive_byte(got); check_byte(got, 8'hf0); end
            join
        end

        send_byte(8'h02);
        for (i = 0; i < 16; i = i + 1)
            send_byte((i[7:0] << 4) | i[7:0]);
        for (i = 15; i >= 0; i = i - 1) begin
            if (i == 0) begin
                fork
                    send_byte(8'h00);
                    receive_byte(got);
                join
            end else begin
                send_byte((i[7:0] << 4) | i[7:0]);
            end
        end
        check_byte(got, 8'hc0);
        receive_byte(got); check_byte(got, 8'h43);
        receive_byte(got); check_byte(got, 8'h24);
        receive_byte(got); check_byte(got, 8'h8e);
        receive_byte(got); check_byte(got, 8'h79);
        receive_byte(got); check_byte(got, 8'hcf);
        receive_byte(got); check_byte(got, 8'ha8);
        receive_byte(got); check_byte(got, 8'h02);
        receive_byte(got); check_byte(got, 8'h85);
        receive_byte(got); check_byte(got, 8'h06);
        receive_byte(got); check_byte(got, 8'h61);
        receive_byte(got); check_byte(got, 8'hcb);
        receive_byte(got); check_byte(got, 8'h3c);
        receive_byte(got); check_byte(got, 8'h8a);
        receive_byte(got); check_byte(got, 8'hed);
        receive_byte(got); check_byte(got, 8'h47);

        if (led[5:4] != 2'b00 || led[2] != 1'b0) begin
            $display("FAIL: UART/core error LEDs set: %02x", led);
            $fatal(1);
        end
        $display("PASS: ULX3S UART bridge STATUS/SET/XOR/MUL");
        $finish;
    end

    initial begin
        #100000000;
        $display("FAIL: simulation timeout");
        $fatal(1);
    end
endmodule
`default_nettype wire

`timescale 1ns/1ps
`default_nettype none

// Public-pin adaptation of tb_lsc1_packet_vector for the synthesized full top.
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
    wire [7:0] uio_in = {1'b0, abort, 2'b00, tx_ready, 2'b00, rx_valid};
    wire [7:0] uio_out, uio_oe;

    reg [7:0] request [0:511];
    reg [7:0] response [0:511];
    integer request_length, response_count = 0, total = 0;
    integer request2_length = 0;
    integer cycle = 0, i;
    reg [1023:0] request_path, request2_path;

    lean_silicon_lsc1_netlist dut (
        .ui_in(rx_data), .uo_out(tx_data), .uio_in(uio_in),
        .uio_out(uio_out), .uio_oe(uio_oe), .ena(1'b1),
        .clk(clk), .rst_n(rst_n)
    );
    assign rx_ready = uio_out[1];
    assign tx_valid = uio_out[2];
    assign busy = uio_out[4];
    assign fault = uio_out[5];
    assign done_pulse = uio_out[7];

    always @(negedge clk) begin
        cycle = cycle + 1;
        tx_ready = (cycle % 5) != 0;
    end

    always @(posedge clk) begin
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

    initial begin
        if (!$value$plusargs("REQUEST=%s", request_path) ||
            !$value$plusargs("LENGTH=%d", request_length))
            $fatal(1, "REQUEST and LENGTH plusargs are required");
        $readmemh(request_path, request);
        repeat (4) @(posedge clk);
        rst_n = 1;
        repeat (2) @(posedge clk);
        for (i = 0; i < request_length; i = i + 1)
            send_byte(request[i], i % 3);
        wait (total != 0 && response_count == total);
        $write("RESPONSE ");
        for (i = 0; i < total; i = i + 1)
            $write("%02x", response[i]);
        $write("\n");
        if ($value$plusargs("REQUEST2=%s", request2_path) &&
            $value$plusargs("LENGTH2=%d", request2_length)) begin
            $readmemh(request2_path, request);
            response_count = 0; total = 0;
            for (i = 0; i < request2_length; i = i + 1)
                send_byte(request[i], i % 3);
            wait (total != 0 && response_count == total);
            $write("RESPONSE ");
            for (i = 0; i < total; i = i + 1)
                $write("%02x", response[i]);
            $write("\n");
        end
        $finish;
    end

    initial begin
        #20_000_000;
        $fatal(1, "synthesized vector differential timeout");
    end
endmodule

`default_nettype wire

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
    integer cycle = 0, i;
    reg [1023:0] request_path;

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
        $finish;
    end

    initial begin
        #20_000_000;
        $fatal(1, "vector differential timeout");
    end
endmodule

`default_nettype wire

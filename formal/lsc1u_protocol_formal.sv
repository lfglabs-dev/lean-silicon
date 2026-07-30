`default_nettype none

module lsc1u_protocol_formal;
    (* gclk *) reg clk;
    (* anyseq *) reg rst_n;
    (* anyseq *) reg ena;
    (* anyseq *) reg [7:0] rx_data;
    (* anyseq *) reg rx_valid;
    (* anyseq *) reg tx_ready;
    wire rx_ready, tx_valid, busy, fault, done_pulse;
    wire [7:0] tx_data;

    lsc1u_core dut (
        .clk(clk), .rst_n(rst_n), .ena(ena),
        .rx_data(rx_data), .rx_valid(rx_valid), .rx_ready(rx_ready),
        .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(tx_ready),
        .busy(busy), .fault(fault), .done_pulse(done_pulse)
    );

    reg past_valid;
    reg txn_active;
    reg txn_completed;
    reg [7:0] expected [0:15];
    reg [4:0] expected_count;
    reg [4:0] output_count;
    reg [7:0] xor_a;
    reg [1:0] op;
    reg [5:0] payload_count;
    reg [127:0] mul_a;
    reg [127:0] mul_b;
    integer i;

    function automatic [127:0] gf_mul;
        input [127:0] a_in;
        input [127:0] b_in;
        reg [127:0] a;
        reg [127:0] b;
        reg [127:0] p;
        integer k;
        begin
            a = a_in; b = b_in; p = 0;
            for (k = 0; k < 128; k = k + 1) begin
                if (b[0]) p = p ^ a;
                b = b >> 1;
                a = {a[126:0], 1'b0} ^ (a[127] ? 128'h87 : 128'h0);
            end
            gf_mul = p;
        end
    endfunction

    always @(posedge clk) begin
        past_valid <= 1'b1;
        if (!past_valid)
            assume(!rst_n);

        if (!rst_n) begin
            txn_active <= 0;
            txn_completed <= 0;
            expected_count <= 0;
            output_count <= 0;
            op <= 0;
            payload_count <= 0;
            mul_a <= 0;
            mul_b <= 0;
        end else begin
            if (rx_valid && rx_ready) begin
                if (!busy) begin
                    txn_active <= 1;
                    txn_completed <= 0;
                    output_count <= 0;
                    expected_count <= 0;
                    payload_count <= 0;
                    if (rx_data == 8'h01) op <= 1;
                    else if (rx_data == 8'h02) op <= 2;
                    else if (rx_data == 8'h03) op <= 3;
                    else begin
                        expected[0] <= 8'he0;
                        expected_count <= 1;
                        op <= 0;
                    end
                end else if (op == 1) begin
                    payload_count <= payload_count + 1'b1;
                    if (!payload_count[0])
                        xor_a <= rx_data;
                    else begin
                        expected[output_count] <= xor_a ^ rx_data;
                        expected_count <= output_count + 1'b1;
                    end
                end else if (op == 3) begin
                    payload_count <= payload_count + 1'b1;
                    expected[output_count] <= rx_data;
                    expected_count <= output_count + 1'b1;
                end else if (op == 2) begin
                    payload_count <= payload_count + 1'b1;
                    if (payload_count < 16)
                        mul_a[payload_count*8 +: 8] <= rx_data;
                    else begin
                        mul_b[(payload_count-16)*8 +: 8] <= rx_data;
                        if (payload_count == 31) begin
                            for (i = 0; i < 16; i = i + 1)
                                expected[i] <=
                                    gf_mul(mul_a, {rx_data, mul_b[119:0]})
                                    >> (i*8);
                            expected_count <= 16;
                        end
                    end
                end
            end
            if (tx_valid && tx_ready) begin
                assert(output_count < expected_count);
                assert(tx_data == expected[output_count]);
                output_count <= output_count + 1'b1;
            end
            if (done_pulse)
                txn_completed <= 1'b1;
        end

        if (past_valid && $past(rst_n)) begin
            if ($past(tx_valid && !tx_ready && ena && rst_n)) begin
                assert(tx_valid);
                assert(tx_data == $past(tx_data));
            end
            if (!$past(ena) && ena && rst_n)
                assert(!done_pulse);
            if ($past(!ena) && !ena) begin
                assert(!rx_ready && !tx_valid && !busy && !fault && !done_pulse);
            end
            if ($past(!rst_n)) begin
                assert(!tx_valid && !done_pulse && !busy && !fault);
            end
            assert(!tx_valid || txn_active);
            if (done_pulse)
                assert($past(tx_valid && tx_ready && ena));
            if (txn_completed)
                assert(!done_pulse);
        end

        cover(past_valid && txn_completed);
        cover(past_valid && fault);
    end
endmodule

`default_nettype wire

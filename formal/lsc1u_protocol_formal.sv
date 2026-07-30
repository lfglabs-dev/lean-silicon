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

    reg past_valid = 1'b0;
    reg txn_active;
    reg txn_completed;
    reg [127:0] expected;
    reg [4:0] expected_count;
    reg [4:0] output_count;
    reg [7:0] xor_a;
    reg [1:0] op;
    reg [5:0] payload_count;

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
                        expected[7:0] <= 8'he0;
                        expected_count <= 1;
                        op <= 0;
                    end
                end else if (op == 1) begin
                    payload_count <= payload_count + 1'b1;
                    if (!payload_count[0])
                        xor_a <= rx_data;
                    else begin
                        expected[output_count * 8 +: 8] <= xor_a ^ rx_data;
                        expected_count <= output_count + 1'b1;
                    end
                end else if (op == 3) begin
                    payload_count <= payload_count + 1'b1;
                    expected[output_count * 8 +: 8] <= rx_data;
                    expected_count <= output_count + 1'b1;
                end else if (op == 2) begin
                    payload_count <= payload_count + 1'b1;
                    if (payload_count == 31)
                        expected_count <= 16;
                end
            end
            if (tx_valid && tx_ready) begin
                assert(output_count < expected_count);
                // SET/XOR are checked byte-for-byte here.  MUL arithmetic is
                // exhaustively proved at the reused serial block boundary by
                // gf128_serialize.sby; this harness proves its 16-byte
                // streamed framing and exactly-one-completion behavior.
                if (op != 2)
                    assert(tx_data == expected[output_count * 8 +: 8]);
                output_count <= output_count + 1'b1;
            end
            if (done_pulse && !(rx_valid && rx_ready && !busy))
                txn_completed <= 1'b1;
        end

        if (past_valid && $past(rst_n)) begin
            if (ena && $past(tx_valid && !tx_ready && ena && rst_n)) begin
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

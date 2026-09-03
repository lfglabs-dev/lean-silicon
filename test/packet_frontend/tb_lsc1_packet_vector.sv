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
    integer request2_length = 0, request3_length = 0, request4_length = 0;
    integer request5_length = 0, request6_length = 0, request7_length = 0;
    integer cycle = 0, i;
    integer manifest_fd = 0, manifest_scan = 0, manifest_length = 0;
    integer manifest_current_length = 0;
    integer manifest_index = 0;
    integer trace_rx_blocked = 0, trace_tx_blocked = 0, trace_done = 0;
    integer trace_rx_accepted = 0;
    integer v3_finite_stalls = 0, rx_stable_checks = 0, tx_stable_checks = 0;
    integer transaction_rx_blocked = 0, transaction_tx_blocked = 0;
    integer transaction_done = 0;
    reg [7:0] transaction_opcode = 0;
    reg [31:0] initial_service_seq;
    reg [1023:0] request_path, request2_path, request3_path, request4_path;
    reg [1023:0] request5_path, request6_path, request7_path;
    reg [1023:0] manifest_path, manifest_request_path, manifest_current_path;
    reg tx_was_blocked = 0;
    reg [7:0] blocked_tx_data = 0;
    reg rx_was_blocked = 0;
    reg [7:0] blocked_rx_data = 0;
    reg v3_rx_prefetched = 0;

    lsc1_packet_frontend dut (
        .clk(clk), .rst_n(rst_n), .abort(abort),
        .rx_data(rx_data), .rx_valid(rx_valid), .rx_ready(rx_ready),
        .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(tx_ready),
        .busy(busy), .fault(fault), .done_pulse(done_pulse)
    );

    always @(negedge clk) begin
        cycle = cycle + 1;
        if (v3_finite_stalls)
            // Fixed backpressure ends after cycle 4000; it is not an
            // arbitrary-ready proof or an unbounded fairness assumption.
            tx_ready = cycle >= 4000 || !((cycle % 11) == 4 ||
                                          (cycle % 11) == 5);
        else
            tx_ready = (cycle % 5) != 0;
    end

    always @(posedge clk) begin
        if (rst_n && rx_valid && !rx_ready) trace_rx_blocked = trace_rx_blocked + 1;
        if (rst_n && rx_valid && rx_ready) trace_rx_accepted = trace_rx_accepted + 1;
        if (rst_n && tx_valid && !tx_ready) trace_tx_blocked = trace_tx_blocked + 1;
        if (rst_n && done_pulse) trace_done = trace_done + 1;
        if (rst_n && rx_valid && !rx_ready) transaction_rx_blocked = transaction_rx_blocked + 1;
        if (rst_n && tx_valid && !tx_ready) transaction_tx_blocked = transaction_tx_blocked + 1;
        if (rst_n && done_pulse) transaction_done = transaction_done + 1;
        if (rst_n && v3_finite_stalls && rx_was_blocked) begin
            if (!rx_valid)
                $fatal(1, "RX valid dropped before stalled beat was accepted");
            if (rx_data !== blocked_rx_data)
                $fatal(1, "RX valid data changed before stalled beat was accepted");
            rx_stable_checks = rx_stable_checks + 1;
        end
        if (rst_n && v3_finite_stalls && rx_valid && !rx_ready) begin
            if (!rx_was_blocked)
                blocked_rx_data <= rx_data;
            rx_was_blocked <= 1;
        end else begin
            rx_was_blocked <= 0;
        end
        if (rst_n && tx_was_blocked) begin
            if (!tx_valid)
                $fatal(1, "TX valid dropped before stalled beat was accepted");
            if (tx_data !== blocked_tx_data)
                $fatal(1, "TX valid data changed before stalled beat was accepted");
            tx_stable_checks = tx_stable_checks + 1;
        end
        if (rst_n && tx_valid && !tx_ready) begin
            if (!tx_was_blocked)
                blocked_tx_data <= tx_data;
            tx_was_blocked <= 1;
        end else begin
            tx_was_blocked <= 0;
        end
        if (rst_n && dut.frame_valid && dut.event_ready)
            transaction_opcode = dut.frame_opcode;
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

    task automatic run_request(input [1023:0] path, input integer length,
                               input integer prefetch_next);
        reg [7:0] origin_opcode;
        begin
            $readmemh(path, request);
            response_count = 0; total = 0;
            transaction_rx_blocked = 0;
            transaction_tx_blocked = 0;
            transaction_done = 0;
            transaction_opcode = 0;
            for (i = (v3_finite_stalls && v3_rx_prefetched) ? 1 : 0;
                 i < length; i = i + 1)
                send_byte(request[i], v3_finite_stalls ? ((i * 7 + 3) % 4) : (i % 3));
            if ($test$plusargs("INJECT_RX_STALL")) begin
                wait (!rx_ready);
                @(negedge clk); rx_valid = 1;
                @(posedge clk);
                @(negedge clk); rx_valid = 0;
            end
            if (v3_finite_stalls && prefetch_next &&
                !($test$plusargs("V3_BAD_CRC_RETIRE") && manifest_index == 2) &&
                // Unlike the other RETIRE faults, the next frame does not
                // share the valid request SOF, so do not prefetch before it.
                !($test$plusargs("V3_BAD_SOF_RETIRE") &&
                  (manifest_index == 1 || manifest_index == 2)) &&
                !($test$plusargs("V3_BAD_FLAGS_RETIRE") && manifest_index == 2) &&
                !($test$plusargs("V3_BAD_VERSION_RETIRE") && manifest_index == 2) &&
                !($test$plusargs("V3_SHORT_RETIRE") && manifest_index == 2) &&
                !($test$plusargs("V3_OVERSIZED_RETIRE") && manifest_index == 2)) begin
                // Present the next frame's common SOF while this response owns
                // the frontend.  send_byte holds that genuine input beat until
                // the authored RTL accepts it after the finite TX stall/drain.
                fork
                    begin
                        send_byte(request[0], 0);
                        v3_rx_prefetched = 1;
                    end
                    begin
                        wait (total != 0 && response_count == total);
                    end
                join
            end else begin
                // Any SOF prefetched for this request has now been consumed;
                // the following request must send its own unless we refill it.
                v3_rx_prefetched = 0;
                wait (total != 0 && response_count == total);
            end
            $write("RESPONSE ");
            for (i = 0; i < total; i = i + 1)
                $write("%02x", response[i]);
            $write("\n");
            origin_opcode = (transaction_opcode == 8'h11 ||
                             transaction_opcode == 8'h12)
                ? dut.staged_operation : transaction_opcode;
            $display("RTL_TRANSACTION request_opcode=%02x origin_opcode=%02x status=%02x rx_blocked=%0d tx_blocked=%0d done=%0d",
                     transaction_opcode, origin_opcode, response[2],
                     transaction_rx_blocked, transaction_tx_blocked,
                     transaction_done);
            $display("RTL_STATE valid=%0d pc=%08x fp=%08x retire_seq=%08x result_pending=%0d",
                     dut.state_valid, dut.committed_pc, dut.committed_fp,
                     dut.retire_seq, dut.result_pending || dut.blake_result_pending);
            if (v3_finite_stalls && response[2] == 8'h91)
                $display("RTL_V3_BAD_SERVICE service_pending=%0d",
                         dut.blake_service_pending);
            if (v3_finite_stalls && response[2] == 8'h84)
                $display("RTL_V3_BAD_CRC service_pending=%0d done=%0d",
                         dut.blake_service_pending, trace_done);
            if (v3_finite_stalls && response[2] == 8'h84 &&
                $test$plusargs("V3_BAD_CRC_RETIRE"))
                $display("RTL_V3_BAD_CRC_RETIRE result_pending=%0d txn_id=%08x result_crc=%08x next_pc=%08x next_fp=%08x state_valid=%0d pc=%08x fp=%08x retire_seq=%08x done=%0d parser_state=%0d",
                         dut.blake_result_pending, dut.blake_staged_txn_id,
                         dut.blake_staged_result_crc, dut.blake_staged_next_pc,
                         dut.blake_staged_next_fp, dut.state_valid,
                         dut.committed_pc, dut.committed_fp, dut.retire_seq,
                         trace_done, dut.receiver.state);
            if (v3_finite_stalls && response[2] == 8'h80 &&
                $test$plusargs("V3_BAD_SOF_RETIRE"))
                $display("RTL_V3_BAD_SOF_RETIRE result_pending=%0d txn_id=%08x result_crc=%08x next_pc=%08x next_fp=%08x state_valid=%0d pc=%08x fp=%08x retire_seq=%08x done=%0d parser_state=%0d",
                         dut.blake_result_pending, dut.blake_staged_txn_id,
                         dut.blake_staged_result_crc, dut.blake_staged_next_pc,
                         dut.blake_staged_next_fp, dut.state_valid,
                         dut.committed_pc, dut.committed_fp, dut.retire_seq,
                         trace_done, dut.receiver.state);
            if (v3_finite_stalls && response[2] == 8'h85 &&
                transaction_opcode == 8'h11)
                $display("RTL_V3_RESERVED_SERVICE service_pending=%0d service_seq=%08x txn_id=%08x service_id=%08x state_valid=%0d pc=%08x fp=%08x retire_seq=%08x done=%0d",
                         dut.blake_service_pending, dut.blake_service_seq,
                         dut.blake_staged_txn_id, dut.blake_staged_service_id,
                         dut.state_valid, dut.committed_pc, dut.committed_fp,
                         dut.retire_seq, trace_done);
            // Envelope faults are raised by the receiver before frame_valid,
            // so transaction_opcode intentionally remains zero for this trace.
            if (v3_finite_stalls && response[2] == 8'h85 &&
                $test$plusargs("V3_ENVELOPE_FLAGS_SERVICE"))
                $display("RTL_V3_ENVELOPE_FLAGS_SERVICE service_pending=%0d service_seq=%08x txn_id=%08x service_id=%08x state_valid=%0d pc=%08x fp=%08x retire_seq=%08x done=%0d",
                         dut.blake_service_pending, dut.blake_service_seq,
                         dut.blake_staged_txn_id, dut.blake_staged_service_id,
                         dut.state_valid, dut.committed_pc, dut.committed_fp,
                         dut.retire_seq, trace_done);
            if (v3_finite_stalls && response[2] == 8'h85 &&
                $test$plusargs("V3_BAD_FLAGS_RETIRE"))
                $display("RTL_V3_BAD_FLAGS_RETIRE result_pending=%0d txn_id=%08x result_crc=%08x next_pc=%08x next_fp=%08x state_valid=%0d pc=%08x fp=%08x retire_seq=%08x done=%0d parser_state=%0d",
                         dut.blake_result_pending, dut.blake_staged_txn_id,
                         dut.blake_staged_result_crc, dut.blake_staged_next_pc,
                         dut.blake_staged_next_fp, dut.state_valid,
                         dut.committed_pc, dut.committed_fp, dut.retire_seq,
                         trace_done, dut.receiver.state);
            if (v3_finite_stalls && response[2] == 8'h81 &&
                $test$plusargs("V3_BAD_VERSION_SERVICE"))
                $display("RTL_V3_BAD_VERSION_SERVICE service_pending=%0d service_seq=%08x txn_id=%08x service_id=%08x state_valid=%0d pc=%08x fp=%08x retire_seq=%08x done=%0d",
                         dut.blake_service_pending, dut.blake_service_seq,
                         dut.blake_staged_txn_id, dut.blake_staged_service_id,
                         dut.state_valid, dut.committed_pc, dut.committed_fp,
                         dut.retire_seq, trace_done);
            if (v3_finite_stalls && response[2] == 8'h81 &&
                $test$plusargs("V3_BAD_VERSION_RETIRE"))
                $display("RTL_V3_BAD_VERSION_RETIRE result_pending=%0d txn_id=%08x result_crc=%08x next_pc=%08x next_fp=%08x state_valid=%0d pc=%08x fp=%08x retire_seq=%08x done=%0d parser_state=%0d",
                         dut.blake_result_pending, dut.blake_staged_txn_id,
                         dut.blake_staged_result_crc, dut.blake_staged_next_pc,
                         dut.blake_staged_next_fp, dut.state_valid,
                         dut.committed_pc, dut.committed_fp, dut.retire_seq,
                         trace_done, dut.receiver.state);
            if (v3_finite_stalls && response[2] == 8'h82 &&
                $test$plusargs("V3_UNKNOWN_OPCODE_SERVICE"))
                $display("RTL_V3_UNKNOWN_OPCODE_SERVICE service_pending=%0d service_seq=%08x txn_id=%08x service_id=%08x state_valid=%0d pc=%08x fp=%08x retire_seq=%08x done=%0d",
                         dut.blake_service_pending, dut.blake_service_seq,
                         dut.blake_staged_txn_id, dut.blake_staged_service_id,
                         dut.state_valid, dut.committed_pc, dut.committed_fp,
                         dut.retire_seq, trace_done);
            if (v3_finite_stalls && response[2] == 8'h83 &&
                transaction_opcode == 8'h11 && dut.receiver.frame_length == 16'd41)
                $display("RTL_V3_SHORT_SERVICE service_pending=%0d service_seq=%08x txn_id=%08x service_id=%08x state_valid=%0d pc=%08x fp=%08x retire_seq=%08x done=%0d",
                         dut.blake_service_pending, dut.blake_service_seq,
                         dut.blake_staged_txn_id, dut.blake_staged_service_id,
                         dut.state_valid, dut.committed_pc, dut.committed_fp,
                         dut.retire_seq, trace_done);
            if (v3_finite_stalls && response[2] == 8'h83 &&
                transaction_opcode == 8'h11 && dut.receiver.frame_length == 16'd43)
                $display("RTL_V3_LENGTH_SERVICE payload_length=%0d service_pending=%0d service_seq=%08x txn_id=%08x service_id=%08x state_valid=%0d pc=%08x fp=%08x retire_seq=%08x done=%0d",
                         dut.receiver.frame_length, dut.blake_service_pending,
                         dut.blake_service_seq, dut.blake_staged_txn_id,
                         dut.blake_staged_service_id, dut.state_valid,
                         dut.committed_pc, dut.committed_fp,
                         dut.retire_seq, trace_done);
            if (v3_finite_stalls && response[2] == 8'h83 &&
                transaction_opcode == 8'h12 && dut.receiver.frame_length == 16'd7 &&
                $test$plusargs("V3_SHORT_RETIRE"))
                $display("RTL_V3_SHORT_RETIRE payload_length=%0d result_pending=%0d txn_id=%08x result_crc=%08x next_pc=%08x next_fp=%08x state_valid=%0d pc=%08x fp=%08x retire_seq=%08x done=%0d parser_state=%0d",
                         dut.receiver.frame_length, dut.blake_result_pending,
                         dut.blake_staged_txn_id, dut.blake_staged_result_crc,
                         dut.blake_staged_next_pc, dut.blake_staged_next_fp,
                         dut.state_valid, dut.committed_pc, dut.committed_fp,
                         dut.retire_seq, trace_done, dut.receiver.state);
            if (v3_finite_stalls && response[2] == 8'h83 &&
                transaction_opcode == 8'h12 && dut.receiver.frame_length == 16'd9 &&
                $test$plusargs("V3_OVERSIZED_RETIRE"))
                $display("RTL_V3_OVERSIZED_RETIRE payload_length=%0d result_pending=%0d txn_id=%08x result_crc=%08x next_pc=%08x next_fp=%08x state_valid=%0d pc=%08x fp=%08x retire_seq=%08x done=%0d parser_state=%0d",
                         dut.receiver.frame_length, dut.blake_result_pending,
                         dut.blake_staged_txn_id, dut.blake_staged_result_crc,
                         dut.blake_staged_next_pc, dut.blake_staged_next_fp,
                         dut.state_valid, dut.committed_pc, dut.committed_fp,
                         dut.retire_seq, trace_done, dut.receiver.state);
            if (v3_finite_stalls && response[2] == 8'h87 &&
                transaction_opcode == 8'h08)
                $display("RTL_V3_DUPLICATE_PENDING service_pending=%0d service_seq=%08x txn_id=%08x service_id=%08x state_valid=%0d pc=%08x fp=%08x retire_seq=%08x done=%0d",
                         dut.blake_service_pending, dut.blake_service_seq,
                         dut.blake_staged_txn_id, dut.blake_staged_service_id,
                         dut.state_valid, dut.committed_pc, dut.committed_fp,
                         dut.retire_seq, trace_done);
            if (v3_finite_stalls && response[2] == 8'h8c)
                $display("RTL_V3_WRITE_CONFLICT service_pending=%0d result_pending=%0d done=%0d",
                         dut.blake_service_pending, dut.blake_result_pending,
                         trace_done);
        end
    endtask

    initial begin
        v3_finite_stalls = $test$plusargs("V3_FINITE_STALLS");
        if (!$value$plusargs("MANIFEST=%s", manifest_path) &&
            (!$value$plusargs("REQUEST=%s", request_path) ||
             !$value$plusargs("LENGTH=%d", request_length)))
            $fatal(1, "MANIFEST or REQUEST and LENGTH plusargs are required");
        repeat (4) @(posedge clk);
        rst_n = 1;
        repeat (2) @(posedge clk);
        if ($test$plusargs("TRACE_IDLE_RX_BLOCKED") ||
            $test$plusargs("TRACE_VALID_RX_BLOCKED")) begin
            @(negedge clk);
            force rx_ready = 0;
            rx_valid = $test$plusargs("TRACE_VALID_RX_BLOCKED");
            @(posedge clk);
            @(negedge clk);
            release rx_ready;
            rx_valid = 0;
            $display("RTL_COUNTS rx_blocked=%0d tx_blocked=%0d done=%0d",
                     trace_rx_blocked, trace_tx_blocked, trace_done);
            $finish;
        end
        if ($value$plusargs("SERVICE_SEQ=%h", initial_service_seq))
            dut.blake3_lifecycle.service_seq = initial_service_seq;
        if (manifest_path != 0) begin
            manifest_fd = $fopen(manifest_path, "r");
            if (!manifest_fd) $fatal(1, "cannot open request manifest");
            manifest_scan = $fscanf(manifest_fd, "%s %d\n",
                                     manifest_request_path, manifest_length);
            while (manifest_scan == 2) begin
                manifest_current_path = manifest_request_path;
                manifest_current_length = manifest_length;
                manifest_scan = $fscanf(manifest_fd, "%s %d\n",
                                         manifest_request_path, manifest_length);
                run_request(manifest_current_path, manifest_current_length,
                            manifest_scan == 2);
                manifest_index = manifest_index + 1;
            end
            $fclose(manifest_fd);
            @(negedge clk);
            if (v3_finite_stalls && dut.receiver.state !== 3'd0)
                $fatal(1, "final v3 replay left RX parser non-idle");
            if (v3_finite_stalls)
                $display("RTL_V3_FINAL rx_accepted=%0d rx_valid=%0d parser_state=%0d",
                         trace_rx_accepted, rx_valid, dut.receiver.state);
            $display("RTL_COUNTS rx_blocked=%0d tx_blocked=%0d done=%0d",
                     trace_rx_blocked, trace_tx_blocked, trace_done);
            if (v3_finite_stalls)
                $display("RTL_V3_STABILITY rx_checks=%0d tx_checks=%0d",
                         rx_stable_checks, tx_stable_checks);
            $finish;
        end
        run_request(request_path, request_length, 0);
        if ($test$plusargs("ABORT_AFTER_FIRST")) begin
            $display("RTL_CONTROL ABORT BEFORE origin_opcode=%02x result=%0d service=%0d tx=%0d",
                     dut.staged_operation, dut.result_pending || dut.blake_result_pending,
                     dut.blake_service_pending, tx_valid);
            @(negedge clk); abort = 1;
            @(posedge clk);
            @(negedge clk); abort = 0;
            #1 $display("RTL_CONTROL ABORT AFTER origin_opcode=%02x result=%0d service=%0d tx=%0d",
                        dut.staged_operation, dut.result_pending || dut.blake_result_pending,
                        dut.blake_service_pending, tx_valid);
        end
        if ($test$plusargs("RESET_AFTER_FIRST")) begin
            $display("RTL_CONTROL RESET BEFORE origin_opcode=%02x result=%0d service=%0d tx=%0d",
                     dut.staged_operation, dut.result_pending || dut.blake_result_pending,
                     dut.blake_service_pending, tx_valid);
            @(negedge clk); rst_n = 0;
            repeat (2) @(posedge clk);
            @(negedge clk); rst_n = 1;
            #1 $display("RTL_CONTROL RESET AFTER origin_opcode=%02x result=%0d service=%0d tx=%0d",
                        dut.staged_operation, dut.result_pending || dut.blake_result_pending,
                        dut.blake_service_pending, tx_valid);
        end
        if ($value$plusargs("REQUEST2=%s", request2_path) &&
            $value$plusargs("LENGTH2=%d", request2_length)) run_request(request2_path, request2_length, 0);
        if ($value$plusargs("REQUEST3=%s", request3_path) &&
            $value$plusargs("LENGTH3=%d", request3_length)) run_request(request3_path, request3_length, 0);
        if ($value$plusargs("REQUEST4=%s", request4_path) &&
            $value$plusargs("LENGTH4=%d", request4_length)) run_request(request4_path, request4_length, 0);
        if ($value$plusargs("REQUEST5=%s", request5_path) &&
            $value$plusargs("LENGTH5=%d", request5_length)) run_request(request5_path, request5_length, 0);
        if ($value$plusargs("REQUEST6=%s", request6_path) &&
            $value$plusargs("LENGTH6=%d", request6_length)) run_request(request6_path, request6_length, 0);
        if ($value$plusargs("REQUEST7=%s", request7_path) &&
            $value$plusargs("LENGTH7=%d", request7_length)) run_request(request7_path, request7_length, 0);
        $display("RTL_COUNTS rx_blocked=%0d tx_blocked=%0d done=%0d",
                 trace_rx_blocked, trace_tx_blocked, trace_done);
        if (v3_finite_stalls)
            $display("RTL_V3_STABILITY rx_checks=%0d tx_checks=%0d",
                     rx_stable_checks, tx_stable_checks);
        $finish;
    end

    initial begin
        #20_000_000;
        $fatal(1, "vector differential timeout");
    end
endmodule

`default_nettype wire

`default_nettype none

// Packet endpoint for the scalar LSC-1 instruction set.  Results are staged
// and become committed only on a matching RETIRE frame.  The explicit stream
// adapter below preserves the product top's 8-bit ready/valid ASIC boundary.
module lsc1_packet_frontend (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       abort,
    input  wire [7:0] rx_data,
    input  wire       rx_valid,
    output wire       rx_ready,
    output wire [7:0] tx_data,
    output wire       tx_valid,
    input  wire       tx_ready,
    output wire       busy,
    output reg        fault,
    output reg        done_pulse
);
    localparam [7:0] OP_XOR = 8'h01, OP_MUL = 8'h02, OP_SET = 8'h03,
                     OP_DEREF_CELL = 8'h04, OP_DEREF_PC = 8'h05,
                     OP_DEREF_FP = 8'h06, OP_JUMP = 8'h07,
                     OP_NEGOTIATE = 8'h10, OP_RETIRE = 8'h12,
                     OP_STATUS = 8'h13;
    localparam [7:0] OK = 8'h00, RETIRED = 8'h02, INFO = 8'h03,
                     BAD_OPCODE = 8'h82, BAD_LENGTH = 8'h83,
                     BAD_FLAGS = 8'h85, BAD_PROFILE = 8'h86,
                     BAD_STATE = 8'h87, BAD_CELL = 8'h88,
                     U32_OVERFLOW = 8'h89, BAD_POINTER = 8'h8a,
                     BAD_INVERSE = 8'h8b,
                     WRITE_CONFLICT = 8'h8c,
                     DEREF_MISMATCH = 8'h8d,
                     MUL_BACKSOLVE_ZERO = 8'h8e,
                     BAD_BRANCH_PROPOSAL = 8'h8f,
                     UNSUPPORTED_IN_PROFILE = 8'h90,
                     RETIRE_MISMATCH = 8'h92,
                     STATE_MISMATCH = 8'h94, INDEX_RANGE = 8'h95,
                     ALIAS_INCONSISTENT = 8'h96;
    localparam [3:0] C_IDLE = 4'd0, C_VERIFY_INVERSE = 4'd1,
                     C_SOLVE = 4'd2, C_FORWARD = 4'd3,
                     C_SET = 4'd4, C_XOR_SOLVE = 4'd5,
                     C_DEREF_POINTER = 4'd6, C_DEREF_VALUE = 4'd7,
                     C_JUMP_INVERSE = 4'd8, C_JUMP_PC = 4'd9,
                     C_JUMP_FP = 4'd10;

    wire frame_valid, rx_fault_valid;
    wire parser_rx_ready;
    wire rx_busy;
    wire [7:0] frame_opcode, rx_fault_status;
    wire [15:0] frame_length;
    wire [2047:0] frame_payload;
    wire tx_busy;
    wire tx_done;
    wire [31:0] tx_payload_crc;
    reg tx_start;
    reg [7:0] tx_status;
    reg [15:0] tx_length;
    reg [543:0] tx_payload;
    reg capture_result_crc;
    reg [3:0] compute_state;
    reg alu_start;
    reg [7:0] alu_operation;
    reg [127:0] alu_operand_a, alu_operand_b;
    wire alu_busy, alu_done, alu_fault;
    wire [127:0] alu_result;
    reg encoder_start;
    reg [15:0] encoder_index;
    wire encoder_busy, encoder_done, encoder_fault;
    wire [127:0] encoder_result;
    wire lane_enable = !tx_busy && !tx_start &&
                       compute_state == C_IDLE && !alu_busy && !encoder_busy;

    reg result_pending;
    reg [31:0] staged_txn_id, staged_next_pc, staged_next_fp;
    reg [31:0] staged_result_crc;
    reg state_valid;
    reg [31:0] committed_pc, committed_fp, retire_seq;
    reg [7:0] active_profile, last_status, last_fault;

    wire event_valid = frame_valid || rx_fault_valid;
    wire event_ready = !tx_busy && !tx_start &&
                       compute_state == C_IDLE;

    lsc1_packet_rx receiver (
        .clk(clk), .rst_n(rst_n), .abort(abort),
        .rx_data(rx_data), .rx_valid(rx_valid && lane_enable), .rx_ready(parser_rx_ready),
        .frame_valid(frame_valid), .frame_ready(event_ready),
        .frame_opcode(frame_opcode), .frame_length(frame_length),
        .frame_payload(frame_payload),
        .fault_valid(rx_fault_valid), .fault_status(rx_fault_status),
        .busy(rx_busy)
    );

    lsc1_packet_tx transmitter (
        .clk(clk), .rst_n(rst_n), .abort(abort),
        .start(tx_start), .status(tx_status), .payload_length(tx_length),
        .payload(tx_payload), .busy(tx_busy), .done_pulse(tx_done),
        .payload_crc(tx_payload_crc),
        .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(tx_ready)
    );

    lsc1_stream_adapter adapter (
        .clk(clk), .rst_n(rst_n), .abort(abort), .start(alu_start),
        .operation(alu_operation), .operand_a(alu_operand_a),
        .operand_b(alu_operand_b), .busy(alu_busy),
        .done_pulse(alu_done), .fault(alu_fault), .result(alu_result)
    );

    lsc1_field_encoder field_encoder (
        .clk(clk), .rst_n(rst_n), .abort(abort), .start(encoder_start),
        .index(encoder_index), .busy(encoder_busy), .done_pulse(encoder_done),
        .fault(encoder_fault), .result(encoder_result)
    );

    assign rx_ready = parser_rx_ready && lane_enable;
    assign busy = rx_busy || tx_busy || tx_start || event_valid || result_pending ||
                  compute_state != C_IDLE || alu_busy || encoder_busy;

`ifdef FORMAL_FULL_LSC1
    full_lsc1_controller_invariants formal_controller_invariants (
        .clk(clk), .rst_n(rst_n), .abort(abort), .rx_ready(rx_ready),
        .tx_valid(tx_valid), .tx_ready(tx_ready), .tx_data(tx_data),
        .busy(busy), .fault(fault), .done_pulse(done_pulse),
        .frame_valid(frame_valid), .rx_fault_valid(rx_fault_valid),
        .tx_start(tx_start), .tx_busy(tx_busy), .compute_state(compute_state),
        .alu_busy(alu_busy), .encoder_busy(encoder_busy),
        .result_pending(result_pending)
    );
`endif

    task automatic emit_fault;
        input [7:0] status;
        input [31:0] txn;
        input [7:0] detail;
        reg [543:0] bytes;
        begin
            bytes = 0;
            bytes[0 +: 32] = txn;
            bytes[32 +: 8] = detail;
            tx_status <= status;
            tx_length <= 5;
            tx_payload <= bytes;
            tx_start <= 1'b1;
            fault <= 1'b1;
            last_status <= status;
            last_fault <= status;
        end
    endtask

    function automatic cell_is_malformed;
        input [7:0] present;
        input [127:0] value;
        begin
            cell_is_malformed = present > 1 || (!present && value != 0);
        end
    endfunction

    integer n_writes, n_deferred, result_length;
    reg [31:0] txn_id, pc, fp, off_a, off_b, off_c;
    reg [31:0] addr_a, addr_b, addr_c;
    reg [31:0] base_index, proposed_pc, proposed_fp;
    reg [31:0] next_pc_value, next_fp_value;
    reg [31:0] deferred_target, deferred_local;
    reg [7:0] profile, pres_a, pres_b, pres_c, inv_present;
    reg [7:0] taken_proposal;
    reg [127:0] val_a, val_b, val_c, inv_value, result_value;
    reg [127:0] solved_a, solved_b;
    reg [543:0] result_bytes, retired_bytes;
    reg [31:0] write_address;
    reg [127:0] write_value;
    reg [7:0] decision_fault, decision_detail;
    reg decision_ok, decision_deferred;

    task automatic emit_result(input [7:0] access_count);
        begin
            result_bytes = 0;
            result_bytes[0 +: 32] = txn_id;
            result_bytes[32 +: 32] = next_pc_value;
            result_bytes[64 +: 32] = next_fp_value;
            result_bytes[96 +: 8] = n_writes;
            if (n_writes != 0) begin
                result_bytes[104 +: 32] = write_address;
                result_bytes[136 +: 128] = write_value;
                result_bytes[264 +: 8] = 0; // n_deferred
                result_bytes[272 +: 8] = access_count;
                result_bytes[280 +: 32] = addr_a;
                if (access_count == 3) begin
                    result_bytes[312 +: 32] = addr_b;
                    result_bytes[344 +: 32] = addr_c;
                    result_length = 47;
                end else begin
                    result_length = 39;
                end
            end else if (n_deferred != 0) begin
                result_bytes[104 +: 8] = 1;
                result_bytes[112 +: 32] = deferred_target;
                result_bytes[144 +: 32] = deferred_local;
                result_bytes[176 +: 8] = access_count;
                result_bytes[184 +: 32] = addr_a;
                result_bytes[216 +: 32] = addr_b;
                result_bytes[248 +: 32] = addr_c;
                result_length = 35;
            end else begin
                result_bytes[104 +: 8] = 0;
                result_bytes[112 +: 8] = access_count;
                result_bytes[120 +: 32] = addr_a;
                if (access_count == 3) begin
                    result_bytes[152 +: 32] = addr_b;
                    result_bytes[184 +: 32] = addr_c;
                    result_length = 27;
                end else result_length = 19;
            end
            staged_txn_id <= txn_id;
            staged_next_pc <= next_pc_value;
            staged_next_fp <= next_fp_value;
            staged_result_crc <= 0;
            capture_result_crc <= 1'b1;
            result_pending <= 1'b1;
            tx_status <= OK;
            tx_length <= result_length;
            tx_payload <= result_bytes;
            tx_start <= 1'b1;
            fault <= 1'b0;
            last_status <= OK;
        end
    endtask

    task automatic finish_binary(input [127:0] product);
        begin
            if (pres_c && val_c != product) begin
                compute_state <= C_IDLE;
                emit_fault(WRITE_CONFLICT, txn_id, 0);
            end else begin
                if (!pres_c) begin
                    write_address = addr_c;
                    write_value = product;
                    n_writes = 1;
                end
                emit_result(3);
                compute_state <= C_IDLE;
            end
        end
    endtask

    task automatic finish_deref_pointer;
        begin
            if (encoder_fault || encoder_result != val_a) begin
                compute_state <= C_IDLE;
                emit_fault(BAD_POINTER, txn_id, 0);
            end else if (frame_opcode == OP_DEREF_CELL) begin
                compute_state <= C_IDLE;
                if (profile == 0 && !pres_c) begin
                    emit_fault(UNSUPPORTED_IN_PROFILE, txn_id, 0);
                end else if (pres_b && pres_c && val_b != val_c) begin
                    emit_fault(DEREF_MISMATCH, txn_id, 0);
                end else begin
                    if (pres_b && !pres_c) begin
                        n_writes = 1;
                        write_address = addr_c;
                        write_value = val_b;
                    end else if (!pres_b && pres_c) begin
                        n_writes = 1;
                        write_address = addr_b;
                        write_value = val_c;
                    end else if (!pres_b && !pres_c) begin
                        n_deferred = 1;
                        deferred_target = addr_b;
                        deferred_local = addr_c;
                    end
                    emit_result(3);
                end
            end else begin
                encoder_index <= frame_opcode == OP_DEREF_PC
                    ? pc[15:0] + 16'd2 : fp[15:0];
                encoder_start <= 1'b1;
                compute_state <= C_DEREF_VALUE;
            end
        end
    endtask

    always @(posedge clk) begin
        if (!rst_n) begin
            tx_start <= 1'b0;
            tx_status <= 0;
            tx_length <= 0;
            tx_payload <= 0;
            capture_result_crc <= 1'b0;
            compute_state <= C_IDLE;
            alu_start <= 1'b0;
            alu_operation <= 0;
            alu_operand_a <= 0;
            alu_operand_b <= 0;
            encoder_start <= 1'b0;
            encoder_index <= 0;
            result_pending <= 1'b0;
            staged_txn_id <= 0;
            staged_next_pc <= 0;
            staged_next_fp <= 0;
            staged_result_crc <= 0;
            state_valid <= 1'b0;
            committed_pc <= 0;
            committed_fp <= 0;
            retire_seq <= 0;
            active_profile <= 1;
            last_status <= OK;
            last_fault <= OK;
            fault <= 1'b0;
            done_pulse <= 1'b0;
        end else if (abort) begin
            tx_start <= 1'b0;
            capture_result_crc <= 1'b0;
            compute_state <= C_IDLE;
            alu_start <= 1'b0;
            encoder_start <= 1'b0;
            result_pending <= 1'b0;
            fault <= 1'b1;
            last_status <= 8'h93;
            last_fault <= 8'h93;
            done_pulse <= 1'b0;
        end else begin
            tx_start <= 1'b0;
            alu_start <= 1'b0;
            encoder_start <= 1'b0;
            done_pulse <= 1'b0;
            if (tx_done && capture_result_crc) begin
                staged_result_crc <= tx_payload_crc;
                capture_result_crc <= 1'b0;
            end

            if (encoder_done && compute_state == C_DEREF_POINTER) begin
                finish_deref_pointer();
            end else if (encoder_done && compute_state == C_DEREF_VALUE) begin
                compute_state <= C_IDLE;
                if (encoder_fault) begin
                    emit_fault(BAD_STATE, txn_id, 3);
                end else if (pres_b && val_b != encoder_result) begin
                    emit_fault(WRITE_CONFLICT, txn_id, 0);
                end else begin
                    if (!pres_b) begin
                        n_writes = 1;
                        write_address = addr_b;
                        write_value = encoder_result;
                    end
                    emit_result(3);
                end
            end else if (encoder_done && compute_state == C_JUMP_PC) begin
                if (encoder_fault) begin
                    compute_state <= C_IDLE;
                    emit_fault(BAD_STATE, txn_id, 3);
                end else if (encoder_result != val_b) begin
                    compute_state <= C_IDLE;
                    emit_fault(BAD_POINTER, txn_id, 0);
                end else begin
                    encoder_index <= proposed_fp[15:0];
                    encoder_start <= 1'b1;
                    compute_state <= C_JUMP_FP;
                end
            end else if (encoder_done && compute_state == C_JUMP_FP) begin
                compute_state <= C_IDLE;
                if (encoder_fault) begin
                    emit_fault(BAD_STATE, txn_id, 3);
                end else if (encoder_result != val_c) begin
                    emit_fault(BAD_POINTER, txn_id, 0);
                end else begin
                    next_pc_value = proposed_pc;
                    next_fp_value = proposed_fp;
                    emit_result(3);
                end
            end else if (alu_done && compute_state == C_JUMP_INVERSE) begin
                if (alu_fault || alu_result != 128'h1) begin
                    compute_state <= C_IDLE;
                    emit_fault(BAD_INVERSE, txn_id, 0);
                end else begin
                    encoder_index <= proposed_pc[15:0];
                    encoder_start <= 1'b1;
                    compute_state <= C_JUMP_PC;
                end
            end else if (alu_done && compute_state == C_SET) begin
                if (alu_fault || alu_result != result_value) begin
                    compute_state <= C_IDLE;
                    emit_fault(BAD_STATE, txn_id, 3);
                end else begin
                    compute_state <= C_IDLE;
                    emit_result(1);
                end
            end else if (alu_done && compute_state == C_XOR_SOLVE) begin
                if (!pres_a) solved_a = alu_result;
                else solved_b = alu_result;
                write_address = !pres_a ? addr_a : addr_b;
                write_value = alu_result;
                n_writes = 1;
                alu_operation <= OP_XOR;
                alu_operand_a <= solved_a;
                alu_operand_b <= solved_b;
                alu_start <= 1'b1;
                compute_state <= C_FORWARD;
            end else if (alu_done && compute_state == C_VERIFY_INVERSE) begin
                if (alu_fault || alu_result != 128'h1) begin
                    compute_state <= C_IDLE;
                    emit_fault(BAD_INVERSE, txn_id, 2);
                end else begin
                    alu_operation <= OP_MUL;
                    alu_operand_a <= val_c;
                    alu_operand_b <= inv_value;
                    alu_start <= 1'b1;
                    compute_state <= C_SOLVE;
                end
            end else if (alu_done && compute_state == C_SOLVE) begin
                if (!pres_a) solved_a = alu_result;
                else solved_b = alu_result;
                write_address = !pres_a ? addr_a : addr_b;
                write_value = alu_result;
                n_writes = 1;
                alu_operation <= OP_MUL;
                alu_operand_a <= alu_result;
                alu_operand_b <= pres_a ? val_a : val_b;
                alu_start <= 1'b1;
                compute_state <= C_FORWARD;
            end else if (alu_done && compute_state == C_FORWARD) begin
                if (alu_fault) begin
                    compute_state <= C_IDLE;
                    emit_fault(BAD_STATE, txn_id, 3);
                end else begin
                    finish_binary(alu_result);
                end
            end else if (event_valid && event_ready) begin
                if (rx_fault_valid) begin
                    emit_fault(rx_fault_status, 0,
                               rx_fault_status == BAD_LENGTH ? 1 : 0);
                end else if (frame_opcode == OP_STATUS) begin
                    if (frame_length != 0) begin
                        emit_fault(BAD_LENGTH, 0, 2);
                    end else begin
                        result_bytes = 0;
                        result_bytes[0 +: 8] = result_pending ? 8'h01 : 8'h00;
                        result_bytes[8 +: 32] = result_pending ? staged_txn_id : 0;
                        result_bytes[40 +: 8] = last_status;
                        result_bytes[48 +: 32] = retire_seq;
                        result_bytes[80 +: 8] = last_fault;
                        result_bytes[88 +: 32] = committed_pc;
                        result_bytes[120 +: 32] = committed_fp;
                        result_bytes[152 +: 8] = state_valid;
                        tx_status <= INFO;
                        tx_length <= 20;
                        tx_payload <= result_bytes;
                        tx_start <= 1'b1;
                        fault <= 1'b0;
                        last_status <= INFO;
                    end
                end else if (frame_opcode == OP_NEGOTIATE) begin
                    if (frame_length != 7) begin
                        emit_fault(BAD_LENGTH, 0, 2);
                    end else if (frame_payload[16 +: 8] > 1) begin
                        emit_fault(BAD_PROFILE, 0, 0);
                    end else if (result_pending) begin
                        emit_fault(BAD_STATE, 0, 0);
                    end else if (!(frame_payload[0 +: 8] <= 1 &&
                                   frame_payload[8 +: 8] >= 1)) begin
                        emit_fault(8'h81, 0, 0);
                    end else if (frame_payload[16 +: 8] != 1) begin
                        // This integrated subset implements interpreter-compatible
                        // reconciliation only and advertises that honestly.
                        emit_fault(BAD_PROFILE, 0, 0);
                    end else begin
                        active_profile <= frame_payload[16 +: 8];
                        result_bytes = 0;
                        result_bytes[0 +: 8] = 1;
                        result_bytes[8 +: 8] = frame_payload[16 +: 8];
                        result_bytes[16 +: 16] = 16'd256;
                        result_bytes[32 +: 8] = 16;
                        result_bytes[40 +: 8] = 0;
                        result_bytes[48 +: 32] = 32'h00000002;
                        result_bytes[80 +: 32] = 32'h4c534331;
                        tx_status <= OK;
                        tx_length <= 14;
                        tx_payload <= result_bytes;
                        tx_start <= 1'b1;
                        fault <= 1'b0;
                        last_status <= OK;
                    end
                end else if (frame_opcode == OP_RETIRE) begin
                    txn_id = frame_payload[0 +: 32];
                    if (frame_length != 8) begin
                        emit_fault(BAD_LENGTH, frame_payload[0 +: 32], 2);
                    end else if (!result_pending) begin
                        emit_fault(BAD_STATE, txn_id, 0);
                    end else if (txn_id != staged_txn_id ||
                                 frame_payload[32 +: 32] != staged_result_crc) begin
                        result_pending <= 1'b0;
                        emit_fault(RETIRE_MISMATCH, txn_id,
                                   txn_id != staged_txn_id ? 1 : 2);
                    end else begin
                        committed_pc <= staged_next_pc;
                        committed_fp <= staged_next_fp;
                        state_valid <= 1'b1;
                        retire_seq <= retire_seq + 1'b1;
                        result_pending <= 1'b0;
                        done_pulse <= 1'b1;
                        retired_bytes = 0;
                        retired_bytes[0 +: 32] = txn_id;
                        retired_bytes[32 +: 32] = retire_seq + 1'b1;
                        retired_bytes[64 +: 32] = staged_next_pc;
                        retired_bytes[96 +: 32] = staged_next_fp;
                        tx_status <= RETIRED;
                        tx_length <= 16;
                        tx_payload <= retired_bytes;
                        tx_start <= 1'b1;
                        fault <= 1'b0;
                        last_status <= RETIRED;
                    end
                end else if (frame_opcode != OP_XOR &&
                             frame_opcode != OP_MUL &&
                             frame_opcode != OP_SET &&
                             frame_opcode != OP_DEREF_CELL &&
                             frame_opcode != OP_DEREF_PC &&
                             frame_opcode != OP_DEREF_FP &&
                             frame_opcode != OP_JUMP) begin
                    emit_fault(BAD_OPCODE, 0, 0);
                end else if ((frame_opcode == OP_SET && frame_length != 51) ||
                             (frame_opcode == OP_XOR && frame_length != 77) ||
                             (frame_opcode == OP_MUL && frame_length != 94) ||
                             ((frame_opcode == OP_DEREF_CELL ||
                               frame_opcode == OP_DEREF_PC ||
                               frame_opcode == OP_DEREF_FP) && frame_length != 81) ||
                             (frame_opcode == OP_JUMP && frame_length != 103)) begin
                    emit_fault(BAD_LENGTH, frame_payload[0 +: 32], 2);
                // Match decode_request_payload: malformed payloads are rejected
                // before dispatch sees the pending transaction, and decoder
                // faults do not acquire the payload transaction ID.
                end else if (frame_payload[12*8 +: 8] > 1) begin
                    emit_fault(BAD_PROFILE, 0, 0);
                end else if (frame_payload[13*8 +: 8] != 0) begin
                    emit_fault(BAD_FLAGS, 0, 1);
                end else if (frame_opcode == OP_SET &&
                             cell_is_malformed(frame_payload[34*8 +: 8],
                                               frame_payload[280 +: 128])) begin
                    emit_fault(BAD_CELL, 0, 0);
                end else if ((frame_opcode == OP_DEREF_CELL ||
                              frame_opcode == OP_DEREF_PC ||
                              frame_opcode == OP_DEREF_FP) &&
                             (cell_is_malformed(frame_payload[26*8 +: 8],
                                                frame_payload[216 +: 128]) ||
                              cell_is_malformed(frame_payload[47*8 +: 8],
                                                frame_payload[384 +: 128]) ||
                              cell_is_malformed(frame_payload[64*8 +: 8],
                                                frame_payload[520 +: 128]))) begin
                    emit_fault(BAD_CELL, 0, 0);
                end else if (frame_opcode == OP_JUMP &&
                             (cell_is_malformed(frame_payload[26*8 +: 8],
                                                frame_payload[216 +: 128]) ||
                              cell_is_malformed(frame_payload[43*8 +: 8],
                                                frame_payload[352 +: 128]) ||
                              cell_is_malformed(frame_payload[60*8 +: 8],
                                                frame_payload[488 +: 128]) ||
                              cell_is_malformed(frame_payload[86*8 +: 8],
                                                frame_payload[696 +: 128]))) begin
                    emit_fault(BAD_CELL, 0, 0);
                end else if (frame_opcode == OP_JUMP &&
                             frame_payload[77*8 +: 8] > 1) begin
                    emit_fault(BAD_BRANCH_PROPOSAL, 0, 3);
                end else if ((frame_opcode == OP_XOR || frame_opcode == OP_MUL) &&
                             (cell_is_malformed(frame_payload[26*8 +: 8],
                                                frame_payload[216 +: 128]) ||
                              cell_is_malformed(frame_payload[43*8 +: 8],
                                                frame_payload[352 +: 128]) ||
                              cell_is_malformed(frame_payload[60*8 +: 8],
                                                frame_payload[488 +: 128]) ||
                              (frame_opcode == OP_MUL &&
                               cell_is_malformed(frame_payload[77*8 +: 8],
                                                 frame_payload[624 +: 128])))) begin
                    emit_fault(BAD_CELL, 0, 0);
                end else if (result_pending) begin
                    emit_fault(BAD_STATE, frame_payload[0 +: 32], 0);
                end else begin
                    txn_id = frame_payload[0 +: 32];
                    pc = frame_payload[32 +: 32];
                    fp = frame_payload[64 +: 32];
                    profile = frame_payload[12*8 +: 8];
                    decision_ok = 1'b1;
                    decision_deferred = 1'b0;
                    decision_fault = 0;
                    decision_detail = 0;
                    result_bytes = 0;
                    n_writes = 0;
                    n_deferred = 0;
                    write_address = 0;
                    write_value = 0;
                    deferred_target = 0;
                    deferred_local = 0;
                    next_pc_value = pc + 1'b1;
                    next_fp_value = fp;

                    if (profile != active_profile) begin
                        decision_ok = 1'b0; decision_fault = BAD_PROFILE;
                    end else if (state_valid && (pc != committed_pc || fp != committed_fp)) begin
                        decision_ok = 1'b0; decision_fault = STATE_MISMATCH;
                    end else if (pc >= 32'h00010000 || fp >= 32'h00010000) begin
                        decision_ok = 1'b0; decision_fault = INDEX_RANGE;
                    end

                    if (decision_ok && frame_opcode == OP_SET) begin
                        off_a = frame_payload[112 +: 32];
                        result_value = frame_payload[144 +: 128];
                        pres_a = frame_payload[34*8 +: 8];
                        val_a = frame_payload[280 +: 128];
                        if (off_a > 32'hffffffff - fp) begin
                            decision_ok = 0; decision_fault = U32_OVERFLOW;
                        end else if (pres_a > 1 || (!pres_a && val_a != 0)) begin
                            decision_ok = 0; decision_fault = BAD_CELL;
                        end else if (pres_a && val_a != result_value) begin
                            decision_ok = 0; decision_fault = WRITE_CONFLICT;
                        end else if (!pres_a) begin
                            addr_a = fp + off_a;
                            write_address = addr_a;
                            write_value = result_value;
                            n_writes = 1;
                        end
                        addr_a = fp + off_a;
                        addr_b = 0; addr_c = 0;
                    end else if (decision_ok &&
                                 (frame_opcode == OP_DEREF_CELL ||
                                  frame_opcode == OP_DEREF_PC ||
                                  frame_opcode == OP_DEREF_FP)) begin
                        off_a = frame_payload[112 +: 32];
                        off_b = frame_payload[144 +: 32];
                        off_c = frame_payload[176 +: 32];
                        pres_a = frame_payload[26*8 +: 8];
                        val_a = frame_payload[216 +: 128];
                        base_index = frame_payload[43*8 +: 32];
                        pres_b = frame_payload[47*8 +: 8];
                        val_b = frame_payload[384 +: 128];
                        pres_c = frame_payload[64*8 +: 8];
                        val_c = frame_payload[520 +: 128];
                        if (off_a > 32'hffffffff-fp || off_c > 32'hffffffff-fp ||
                            off_b > 32'hffffffff-base_index) begin
                            decision_ok = 0; decision_fault = U32_OVERFLOW;
                        end else if (base_index >= 32'h00010000 ||
                                     (frame_opcode == OP_DEREF_PC && pc > 32'h0000fffd)) begin
                            decision_ok = 0; decision_fault = INDEX_RANGE;
                        end else if (pres_a > 1 || pres_b > 1 || pres_c > 1 ||
                            (!pres_a && val_a != 0) || (!pres_b && val_b != 0) ||
                            (!pres_c && val_c != 0)) begin
                            decision_ok = 0; decision_fault = BAD_CELL;
                        end else begin
                            addr_a = fp + off_a;
                            addr_b = base_index + off_b;
                            addr_c = fp + off_c;
                            if ((addr_a == addr_b && (pres_a != pres_b || val_a != val_b)) ||
                                (addr_a == addr_c && (pres_a != pres_c || val_a != val_c)) ||
                                (addr_b == addr_c && (pres_b != pres_c || val_b != val_c))) begin
                                decision_ok = 0; decision_fault = ALIAS_INCONSISTENT;
                            end else begin
                                encoder_index <= base_index[15:0];
                                encoder_start <= 1'b1;
                                compute_state <= C_DEREF_POINTER;
                                decision_deferred = 1'b1;
                            end
                        end
                    end else if (decision_ok && frame_opcode == OP_JUMP) begin
                        off_a = frame_payload[112 +: 32];
                        off_b = frame_payload[144 +: 32];
                        off_c = frame_payload[176 +: 32];
                        pres_a = frame_payload[26*8 +: 8];
                        val_a = frame_payload[216 +: 128];
                        pres_b = frame_payload[43*8 +: 8];
                        val_b = frame_payload[352 +: 128];
                        pres_c = frame_payload[60*8 +: 8];
                        val_c = frame_payload[488 +: 128];
                        taken_proposal = frame_payload[77*8 +: 8];
                        proposed_pc = frame_payload[78*8 +: 32];
                        proposed_fp = frame_payload[82*8 +: 32];
                        inv_present = frame_payload[86*8 +: 8];
                        inv_value = frame_payload[696 +: 128];
                        if (off_a > 32'hffffffff-fp || off_b > 32'hffffffff-fp ||
                            off_c > 32'hffffffff-fp) begin
                            decision_ok = 0; decision_fault = U32_OVERFLOW;
                        end else if (pres_a > 1 || pres_b > 1 || pres_c > 1 ||
                            (!pres_a && val_a != 0) || (!pres_b && val_b != 0) ||
                            (!pres_c && val_c != 0) || inv_present > 1 ||
                            (!inv_present && inv_value != 0)) begin
                            decision_ok = 0; decision_fault = BAD_CELL;
                        end else begin
                            addr_a = fp + off_a; addr_b = fp + off_b; addr_c = fp + off_c;
                            if ((addr_a == addr_b && (pres_a != pres_b || val_a != val_b)) ||
                                (addr_a == addr_c && (pres_a != pres_c || val_a != val_c)) ||
                                (addr_b == addr_c && (pres_b != pres_c || val_b != val_c))) begin
                                decision_ok = 0; decision_fault = ALIAS_INCONSISTENT;
                            end else if (taken_proposal > 1) begin
                                decision_ok = 0; decision_fault = BAD_BRANCH_PROPOSAL;
                                decision_detail = 3;
                            end else if (taken_proposal != (val_a != 0)) begin
                                decision_ok = 0; decision_fault = BAD_BRANCH_PROPOSAL;
                                decision_detail = 1;
                            end else if (taken_proposal) begin
                                if (proposed_pc >= 32'h00010000 ||
                                    proposed_fp >= 32'h00010000) begin
                                    decision_ok = 0; decision_fault = INDEX_RANGE;
                                end else if (!inv_present) begin
                                    decision_ok = 0; decision_fault = BAD_INVERSE;
                                end else begin
                                    alu_operation <= OP_MUL;
                                    alu_operand_a <= val_a;
                                    alu_operand_b <= inv_value;
                                    alu_start <= 1'b1;
                                    compute_state <= C_JUMP_INVERSE;
                                    decision_deferred = 1'b1;
                                end
                            end else if ((inv_present && inv_value != 0)) begin
                                decision_ok = 0; decision_fault = BAD_INVERSE;
                                decision_detail = 3;
                            end else if (proposed_pc != 0 || proposed_fp != 0) begin
                                decision_ok = 0; decision_fault = BAD_BRANCH_PROPOSAL;
                                decision_detail = 2;
                            end
                        end
                    end else if (decision_ok) begin
                        off_a = frame_payload[112 +: 32];
                        off_b = frame_payload[144 +: 32];
                        off_c = frame_payload[176 +: 32];
                        pres_a = frame_payload[26*8 +: 8];
                        val_a = frame_payload[216 +: 128];
                        pres_b = frame_payload[43*8 +: 8];
                        val_b = frame_payload[352 +: 128];
                        pres_c = frame_payload[60*8 +: 8];
                        val_c = frame_payload[488 +: 128];
                        inv_present = frame_opcode == OP_MUL ? frame_payload[77*8 +: 8] : 0;
                        inv_value = frame_opcode == OP_MUL ? frame_payload[624 +: 128] : 0;
                        if (off_a > 32'hffffffff-fp || off_b > 32'hffffffff-fp ||
                            off_c > 32'hffffffff-fp) begin
                            decision_ok = 0; decision_fault = U32_OVERFLOW;
                        end else if (pres_a > 1 || pres_b > 1 || pres_c > 1 ||
                            (!pres_a && val_a != 0) || (!pres_b && val_b != 0) ||
                            (!pres_c && val_c != 0) || inv_present > 1 ||
                            (!inv_present && inv_value != 0)) begin
                            decision_ok = 0; decision_fault = BAD_CELL;
                        end else begin
                            addr_a = fp + off_a; addr_b = fp + off_b; addr_c = fp + off_c;
                            if ((addr_a == addr_b && (pres_a != pres_b || val_a != val_b)) ||
                                (addr_a == addr_c && (pres_a != pres_c || val_a != val_c)) ||
                                (addr_b == addr_c && (pres_b != pres_c || val_b != val_c))) begin
                                decision_ok = 0; decision_fault = ALIAS_INCONSISTENT;
                            end
                        end
                        solved_a = val_a; solved_b = val_b;
                        if (decision_ok && pres_c && (pres_a ^ pres_b)) begin
                            if (frame_opcode == OP_XOR) begin
                                alu_operation <= OP_XOR;
                                alu_operand_a <= val_c;
                                alu_operand_b <= pres_a ? val_a : val_b;
                                alu_start <= 1'b1;
                                compute_state <= C_XOR_SOLVE;
                                decision_deferred = 1'b1;
                            end else if ((!pres_a && val_b == 0) || (!pres_b && val_a == 0)) begin
                                decision_ok = 0; decision_fault = MUL_BACKSOLVE_ZERO;
                            end else if (!inv_present) begin
                                decision_ok = 0; decision_fault = BAD_INVERSE;
                            end else begin
                                alu_operation <= OP_MUL;
                                alu_operand_a <= pres_a ? val_a : val_b;
                                alu_operand_b <= inv_value;
                                alu_start <= 1'b1;
                                compute_state <= C_VERIFY_INVERSE;
                                decision_deferred = 1'b1;
                            end
                        end
                        if (decision_ok && !decision_deferred && frame_opcode == OP_MUL) begin
                            alu_operation <= OP_MUL;
                            alu_operand_a <= solved_a;
                            alu_operand_b <= solved_b;
                            alu_start <= 1'b1;
                            compute_state <= C_FORWARD;
                            decision_deferred = 1'b1;
                        end else if (decision_ok && !decision_deferred && frame_opcode == OP_XOR) begin
                            alu_operation <= OP_XOR;
                            alu_operand_a <= solved_a;
                            alu_operand_b <= solved_b;
                            alu_start <= 1'b1;
                            compute_state <= C_FORWARD;
                            decision_deferred = 1'b1;
                        end
                    end

                    if (decision_ok && frame_opcode == OP_SET) begin
                        alu_operation <= OP_SET;
                        alu_operand_a <= result_value;
                        alu_operand_b <= 0;
                        alu_start <= 1'b1;
                        compute_state <= C_SET;
                        decision_deferred = 1'b1;
                    end

                    if (decision_deferred) begin
                        // The shared stream datapath completes and emits the result.
                    end else if (!decision_ok) begin
                        emit_fault(decision_fault, txn_id, decision_detail);
                    end else begin
                        emit_result(frame_opcode == OP_SET ? 1 : 3);
                    end
                end
            end
        end
    end

    wire _unused_adapter_fault = alu_fault;
endmodule

`default_nettype wire

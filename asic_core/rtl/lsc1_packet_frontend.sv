`default_nettype none

// Separable Phase-3 packet endpoint for SET_CONSTANT, XOR, and MUL_NATIVE.
// It deliberately is not instantiated by lean_silicon_lsc1: integration is a
// later ownership boundary.  Results are staged and become committed only on
// a matching RETIRE frame.
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
                     OP_RETIRE = 8'h12;
    localparam [7:0] OK = 8'h00, RETIRED = 8'h02,
                     BAD_OPCODE = 8'h82, BAD_LENGTH = 8'h83,
                     BAD_FLAGS = 8'h85, BAD_PROFILE = 8'h86,
                     BAD_STATE = 8'h87, BAD_CELL = 8'h88,
                     U32_OVERFLOW = 8'h89, BAD_INVERSE = 8'h8b,
                     WRITE_CONFLICT = 8'h8c,
                     MUL_BACKSOLVE_ZERO = 8'h8e,
                     UNSUPPORTED_IN_PROFILE = 8'h90,
                     RETIRE_MISMATCH = 8'h92, ABORTED = 8'h93,
                     STATE_MISMATCH = 8'h94, INDEX_RANGE = 8'h95,
                     ALIAS_INCONSISTENT = 8'h96;
    localparam [1:0] C_IDLE = 2'd0, C_VERIFY_INVERSE = 2'd1,
                     C_SOLVE = 2'd2, C_FORWARD = 2'd3;

    wire frame_valid, rx_fault_valid;
    wire parser_rx_ready;
    wire rx_busy;
    wire lane_enable = !tx_busy && !tx_start && !abort_response_pending &&
                       compute_state == C_IDLE && !mul_busy;
    wire [7:0] frame_opcode, rx_fault_status;
    wire [15:0] frame_length;
    wire [751:0] frame_payload;
    wire tx_busy;
    wire tx_done;
    wire [31:0] tx_payload_crc;
    reg tx_start;
    reg [7:0] tx_status;
    reg [15:0] tx_length;
    reg [543:0] tx_payload;
    reg abort_response_pending;
    reg capture_result_crc;
    reg [1:0] compute_state;
    reg mul_start;
    reg [127:0] mul_operand_a, mul_operand_b;
    wire mul_busy, mul_done;
    wire [127:0] mul_result;

    reg result_pending;
    reg [31:0] staged_txn_id, staged_next_pc, staged_next_fp;
    reg [31:0] staged_result_crc;
    reg state_valid;
    reg [31:0] committed_pc, committed_fp, retire_seq;

    wire event_valid = frame_valid || rx_fault_valid;
    wire event_ready = !tx_busy && !tx_start && !abort_response_pending &&
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

    lsc1_gf128_mul multiplier (
        .clk(clk), .rst_n(rst_n), .abort(abort), .start(mul_start),
        .operand_a(mul_operand_a), .operand_b(mul_operand_b),
        .busy(mul_busy), .done_pulse(mul_done), .result(mul_result)
    );

    assign rx_ready = parser_rx_ready && lane_enable;
    assign busy = rx_busy || tx_busy || tx_start || event_valid || result_pending ||
                  abort_response_pending || compute_state != C_IDLE || mul_busy;

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
        end
    endtask

    integer n_writes, result_length;
    reg [31:0] txn_id, pc, fp, off_a, off_b, off_c;
    reg [31:0] addr_a, addr_b, addr_c;
    reg [7:0] profile, pres_a, pres_b, pres_c, inv_present;
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
            result_bytes[32 +: 32] = pc + 1'b1;
            result_bytes[64 +: 32] = fp;
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
            end else begin
                result_bytes[104 +: 8] = 0; // n_deferred
                result_bytes[112 +: 8] = access_count;
                result_bytes[120 +: 32] = addr_a;
                if (access_count == 3) begin
                    result_bytes[152 +: 32] = addr_b;
                    result_bytes[184 +: 32] = addr_c;
                    result_length = 27;
                end else begin
                    result_length = 19;
                end
            end
            staged_txn_id <= txn_id;
            staged_next_pc <= pc + 1'b1;
            staged_next_fp <= fp;
            staged_result_crc <= 0;
            capture_result_crc <= 1'b1;
            result_pending <= 1'b1;
            tx_status <= OK;
            tx_length <= result_length;
            tx_payload <= result_bytes;
            tx_start <= 1'b1;
            fault <= 1'b0;
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

    always @(posedge clk) begin
        if (!rst_n) begin
            tx_start <= 1'b0;
            tx_status <= 0;
            tx_length <= 0;
            tx_payload <= 0;
            abort_response_pending <= 1'b0;
            capture_result_crc <= 1'b0;
            compute_state <= C_IDLE;
            mul_start <= 1'b0;
            mul_operand_a <= 0;
            mul_operand_b <= 0;
            result_pending <= 1'b0;
            staged_txn_id <= 0;
            staged_next_pc <= 0;
            staged_next_fp <= 0;
            staged_result_crc <= 0;
            state_valid <= 1'b0;
            committed_pc <= 0;
            committed_fp <= 0;
            retire_seq <= 0;
            fault <= 1'b0;
            done_pulse <= 1'b0;
        end else if (abort) begin
            tx_start <= 1'b0;
            abort_response_pending <= 1'b1;
            capture_result_crc <= 1'b0;
            compute_state <= C_IDLE;
            mul_start <= 1'b0;
            result_pending <= 1'b0;
            fault <= 1'b1;
            done_pulse <= 1'b0;
        end else begin
            tx_start <= 1'b0;
            mul_start <= 1'b0;
            done_pulse <= 1'b0;
            if (tx_done && capture_result_crc) begin
                staged_result_crc <= tx_payload_crc;
                capture_result_crc <= 1'b0;
            end

            if (mul_done && compute_state == C_VERIFY_INVERSE) begin
                if (mul_result != 128'h1) begin
                    compute_state <= C_IDLE;
                    emit_fault(BAD_INVERSE, txn_id, 0);
                end else begin
                    mul_operand_a <= val_c;
                    mul_operand_b <= inv_value;
                    mul_start <= 1'b1;
                    compute_state <= C_SOLVE;
                end
            end else if (mul_done && compute_state == C_SOLVE) begin
                if (!pres_a) solved_a = mul_result;
                else solved_b = mul_result;
                write_address = !pres_a ? addr_a : addr_b;
                write_value = mul_result;
                n_writes = 1;
                mul_operand_a <= mul_result;
                mul_operand_b <= pres_a ? val_a : val_b;
                mul_start <= 1'b1;
                compute_state <= C_FORWARD;
            end else if (mul_done && compute_state == C_FORWARD) begin
                finish_binary(mul_result);
            end else if (abort_response_pending && !tx_busy) begin
                abort_response_pending <= 1'b0;
                emit_fault(ABORTED, 0, 0);
            end else if (event_valid && event_ready) begin
                if (rx_fault_valid) begin
                    emit_fault(rx_fault_status, 0, 0);
                end else if (frame_opcode == OP_RETIRE) begin
                    txn_id = frame_payload[0 +: 32];
                    if (frame_length != 8) begin
                        emit_fault(BAD_LENGTH, 0, 2);
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
                    end
                end else if (frame_opcode != OP_XOR &&
                             frame_opcode != OP_MUL &&
                             frame_opcode != OP_SET) begin
                    emit_fault(BAD_OPCODE, 0, 0);
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
                    write_address = 0;
                    write_value = 0;

                    if ((frame_opcode == OP_SET && frame_length != 51) ||
                        (frame_opcode == OP_XOR && frame_length != 77) ||
                        (frame_opcode == OP_MUL && frame_length != 94)) begin
                        decision_ok = 1'b0; decision_fault = BAD_LENGTH; decision_detail = 2;
                    end else if (frame_payload[13*8 +: 8] != 0) begin
                        decision_ok = 1'b0; decision_fault = BAD_FLAGS; decision_detail = 1;
                    end else if (profile > 1) begin
                        decision_ok = 1'b0; decision_fault = BAD_PROFILE;
                    end else if (profile != 1) begin
                        // This Phase-3 subset has no NEGOTIATE control opcode.
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
                                if (!pres_a) solved_a = val_c ^ val_b;
                                else solved_b = val_c ^ val_a;
                            end else if ((!pres_a && val_b == 0) || (!pres_b && val_a == 0)) begin
                                decision_ok = 0; decision_fault = MUL_BACKSOLVE_ZERO;
                            end else if (!inv_present) begin
                                decision_ok = 0; decision_fault = BAD_INVERSE;
                            end else begin
                                mul_operand_a <= pres_a ? val_a : val_b;
                                mul_operand_b <= inv_value;
                                mul_start <= 1'b1;
                                compute_state <= C_VERIFY_INVERSE;
                                decision_deferred = 1'b1;
                            end
                            if (decision_ok && frame_opcode == OP_XOR) begin
                                write_address = !pres_a ? addr_a : addr_b;
                                write_value = !pres_a ? solved_a : solved_b;
                                n_writes = 1;
                            end
                        end
                        if (decision_ok && !decision_deferred && frame_opcode == OP_MUL) begin
                            mul_operand_a <= solved_a;
                            mul_operand_b <= solved_b;
                            mul_start <= 1'b1;
                            compute_state <= C_FORWARD;
                            decision_deferred = 1'b1;
                        end else if (decision_ok && frame_opcode == OP_XOR) begin
                            result_value = solved_a ^ solved_b;
                            if (pres_c && val_c != result_value) begin
                                decision_ok = 0; decision_fault = WRITE_CONFLICT;
                            end else if (!pres_c) begin
                                write_address = addr_c;
                                write_value = result_value;
                                n_writes = 1;
                            end
                        end
                    end

                    if (decision_deferred) begin
                        // The shared multiplier completes and emits the result.
                    end else if (!decision_ok) begin
                        emit_fault(decision_fault, txn_id, decision_detail);
                    end else begin
                        emit_result(frame_opcode == OP_SET ? 1 : 3);
                    end
                end
            end
        end
    end
endmodule

`default_nettype wire

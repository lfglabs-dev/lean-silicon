/*
 * leanVM-b MinCore streaming opcode engine.
 *
 * This is the first, deliberately small proof boundary. It implements the
 * 128-bit value operations used by the scalar ISA; the later full core adds
 * instruction fetch, 32-bit pc/fp indices, and external memory sequencing.
 *
 * Byte order is little-endian. Every transfer occurs on a rising edge when
 * valid && ready.
 *
 * Commands:
 *   0x01 XOR128   : A0,B0,A1,B1,...,A15,B15 -> 16 result bytes
 *   0x02 MUL128   : A0..A15,B0..B15          -> 16 result bytes
 *   0x03 SET128   : V0..V15                  -> 16 echoed bytes
 *   0x04 NONZERO  : V0..V15                  -> one byte (0 or 1)
 *   0x7d CLEAR    : clear sticky fault, no response
 *   0x7e STATUS   : no payload                -> four status bytes
 *
 * XOR, SET, and the final NONZERO byte are combinational stream transforms:
 * input acceptance and output acceptance occur on the same edge. This removes
 * the output byte register and reaches the lane-capacity latency bound.
 *
 * MUL128 uses the real leanVM-b field:
 *   GF(2^128) / (x^128 + x^7 + x^2 + x + 1).
 */
`default_nettype none

module leanvm_b_stream_alu (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       abort,

    input  wire [7:0] rx_data,
    input  wire       rx_valid,
    output reg        rx_ready,

    output reg  [7:0] tx_data,
    output reg        tx_valid,
    input  wire       tx_ready,

    output wire       busy,
    output wire       done_pulse,
    output reg        fault
);

    localparam [7:0] CMD_XOR128  = 8'h01;
    localparam [7:0] CMD_MUL128  = 8'h02;
    localparam [7:0] CMD_SET128  = 8'h03;
    localparam [7:0] CMD_NONZERO = 8'h04;
    localparam [7:0] CMD_CLEAR   = 8'h7d;
    localparam [7:0] CMD_STATUS  = 8'h7e;

    localparam [3:0]
        S_IDLE       = 4'd0,
        S_XOR_A      = 4'd1,
        S_XOR_B      = 4'd2,
        S_SET_STREAM = 4'd3,
        S_ZERO_STREAM= 4'd4,
        S_MUL_A_RX   = 4'd5,
        S_MUL_B_RX   = 4'd6,
        S_MUL_BITS   = 4'd7,
        S_MUL_TX     = 4'd8,
        S_STATUS_TX  = 4'd9,
        S_ERROR_TX   = 4'd10;

    reg [3:0] state;
    reg [3:0] byte_index;

    // One shared scratch register. The live ranges are disjoint:
    //   XOR: saved A byte;
    //   MUL: B[7:1] plus a sentinel marking the last tail bit;
    //   NONZERO: bit 0 is the accumulated nonzero flag.
    reg [7:0] scratch_byte;

    reg  mul_a_valid;
    reg  mul_bit_valid;
    reg  mul_bit_value;
    reg  mul_result_shift;
    wire [7:0] mul_result_byte;

    // Initial tail layout is {sentinel, b7, ..., b1}. Before b7 is
    // processed, the sentinel has shifted into bit 1, so [7:1] == 1.
    wire mul_tail_last = (scratch_byte[7:1] == 7'b0000001);
    wire mul_bit_last =
        (state == S_MUL_BITS) &&
        (byte_index == 4'd15) &&
        mul_tail_last;

    gf128_mul_bitstream multiplier (
        .clk          (clk),
        .rst_n        (rst_n),
        .abort        (abort),
        .a_valid      (mul_a_valid),
        .a_byte       (rx_data),
        .a_last       (byte_index == 4'd15),
        .bit_valid    (mul_bit_valid),
        .bit_value    (mul_bit_value),
        .bit_last     (mul_bit_last),
        .result_shift (mul_result_shift),
        .result_byte  (mul_result_byte)
    );

    assign busy = (state != S_IDLE);

    function automatic [7:0] status_byte;
        input [3:0] index;
        begin
            case (index)
                4'd0: status_byte = 8'h01; // protocol major
                4'd1: status_byte = 8'h01; // protocol minor: combinational streams
                4'd2: status_byte = 8'h0f; // XOR, MUL, SET, NONZERO
                4'd3: status_byte = 8'h08; // external lane width in bits
                default: status_byte = 8'h00;
            endcase
        end
    endfunction

    always @(*) begin
        rx_ready         = 1'b0;
        tx_valid         = 1'b0;
        tx_data          = 8'h00;
        mul_a_valid      = 1'b0;
        mul_bit_valid    = 1'b0;
        mul_bit_value    = 1'b0;
        mul_result_shift = 1'b0;

        case (state)
            S_IDLE: begin
                rx_ready = 1'b1;
            end

            S_XOR_A: begin
                rx_ready = 1'b1;
            end

            S_XOR_B: begin
                // The B byte and result byte transfer atomically.
                tx_valid = rx_valid;
                tx_data  = scratch_byte ^ rx_data;
                rx_ready = tx_ready;
            end

            S_SET_STREAM: begin
                // Pure byte-stream pass-through; no result register.
                tx_valid = rx_valid;
                tx_data  = rx_data;
                rx_ready = tx_ready;
            end

            S_ZERO_STREAM: begin
                if (byte_index == 4'd15) begin
                    // Final input and the one-byte predicate transfer atomically.
                    tx_valid = rx_valid;
                    tx_data  = {7'b0, scratch_byte[0] || (rx_data != 8'h00)};
                    rx_ready = tx_ready;
                end else begin
                    rx_ready = 1'b1;
                end
            end

            S_MUL_A_RX: begin
                rx_ready    = 1'b1;
                mul_a_valid = rx_valid;
            end

            S_MUL_B_RX: begin
                // Consume bit 0 on the same edge that receives the byte.
                rx_ready      = 1'b1;
                mul_bit_valid = rx_valid;
                mul_bit_value = rx_data[0];
            end

            S_MUL_BITS: begin
                mul_bit_valid = 1'b1;
                mul_bit_value = scratch_byte[0];
            end

            S_MUL_TX: begin
                tx_valid         = 1'b1;
                tx_data          = mul_result_byte;
                mul_result_shift = tx_ready;
            end

            S_STATUS_TX: begin
                tx_valid = 1'b1;
                tx_data  = status_byte(byte_index);
            end

            S_ERROR_TX: begin
                tx_valid = 1'b1;
                tx_data  = 8'he0;
            end

            default: begin
                rx_ready = 1'b0;
            end
        endcase
    end

    wire rx_fire = rx_valid && rx_ready;
    wire tx_fire = tx_valid && tx_ready;

    // Exact transaction-completion pulse, including the final output handshake.
    assign done_pulse =
        (rx_fire && (state == S_IDLE) && (rx_data == CMD_CLEAR)) ||
        (tx_fire && (
            ((state == S_XOR_B)       && (byte_index == 4'd15)) ||
            ((state == S_SET_STREAM)  && (byte_index == 4'd15)) ||
            ((state == S_ZERO_STREAM) && (byte_index == 4'd15)) ||
            ((state == S_MUL_TX)      && (byte_index == 4'd15)) ||
            ((state == S_STATUS_TX)   && (byte_index == 4'd3))  ||
            (state == S_ERROR_TX)));

    always @(posedge clk) begin
        if (!rst_n) begin
            state        <= S_IDLE;
            byte_index   <= 4'b0;
            scratch_byte <= 8'b0;
            fault        <= 1'b0;
        end else if (abort) begin
            state        <= S_IDLE;
            byte_index   <= 4'b0;
            scratch_byte <= 8'b0;
            fault        <= 1'b1;
        end else begin
            case (state)
                S_IDLE: begin
                    byte_index   <= 4'b0;
                    scratch_byte <= 8'b0;

                    if (rx_fire) begin
                        case (rx_data)
                            CMD_XOR128:  state <= S_XOR_A;
                            CMD_MUL128:  state <= S_MUL_A_RX;
                            CMD_SET128:  state <= S_SET_STREAM;
                            CMD_NONZERO: state <= S_ZERO_STREAM;
                            CMD_STATUS:  state <= S_STATUS_TX;
                            CMD_CLEAR: begin
                                fault <= 1'b0;
                                state <= S_IDLE;
                            end
                            default: begin
                                fault <= 1'b1;
                                state <= S_ERROR_TX;
                            end
                        endcase
                    end
                end

                S_XOR_A: begin
                    if (rx_fire) begin
                        scratch_byte <= rx_data;
                        state        <= S_XOR_B;
                    end
                end

                S_XOR_B: begin
                    if (tx_fire) begin
                        if (byte_index == 4'd15) begin
                            state <= S_IDLE;
                        end else begin
                            byte_index <= byte_index + 1'b1;
                            state      <= S_XOR_A;
                        end
                    end
                end

                S_SET_STREAM: begin
                    if (tx_fire) begin
                        if (byte_index == 4'd15) begin
                            state <= S_IDLE;
                        end else begin
                            byte_index <= byte_index + 1'b1;
                        end
                    end
                end

                S_ZERO_STREAM: begin
                    if (byte_index == 4'd15) begin
                        if (tx_fire)
                            state <= S_IDLE;
                    end else if (rx_fire) begin
                        scratch_byte[0] <=
                            scratch_byte[0] || (rx_data != 8'h00);
                        byte_index <= byte_index + 1'b1;
                    end
                end

                S_MUL_A_RX: begin
                    if (rx_fire) begin
                        if (byte_index == 4'd15) begin
                            byte_index <= 4'b0;
                            state      <= S_MUL_B_RX;
                        end else begin
                            byte_index <= byte_index + 1'b1;
                        end
                    end
                end

                S_MUL_B_RX: begin
                    if (rx_fire) begin
                        scratch_byte <= {1'b1, rx_data[7:1]};
                        state        <= S_MUL_BITS;
                    end
                end

                S_MUL_BITS: begin
                    if (mul_tail_last) begin
                        if (byte_index == 4'd15) begin
                            byte_index <= 4'b0;
                            state      <= S_MUL_TX;
                        end else begin
                            byte_index <= byte_index + 1'b1;
                            state      <= S_MUL_B_RX;
                        end
                    end else begin
                        scratch_byte <= scratch_byte >> 1;
                    end
                end

                S_MUL_TX: begin
                    if (tx_fire) begin
                        if (byte_index == 4'd15) begin
                            state <= S_IDLE;
                        end else begin
                            byte_index <= byte_index + 1'b1;
                        end
                    end
                end

                S_STATUS_TX: begin
                    if (tx_fire) begin
                        if (byte_index == 4'd3) begin
                            state <= S_IDLE;
                        end else begin
                            byte_index <= byte_index + 1'b1;
                        end
                    end
                end

                S_ERROR_TX: begin
                    if (tx_fire)
                        state <= S_IDLE;
                end

                default: begin
                    fault <= 1'b1;
                    state <= S_ERROR_TX;
                end
            endcase
        end
    end

endmodule

`default_nettype wire

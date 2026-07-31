/*
 * LSC-1u: Tiny Tapeout streamed arithmetic/checking sub-core of LSC-1.
 *
 * This is deliberately not the full packet interface. Each accepted command
 * has a fixed payload and response width:
 *   0x01 XOR: A0,B0,...,A15,B15 -> R0..R15
 *   0x02 MUL: A0..A15,B0..B15   -> R0..R15
 *   0x03 SET: V0..V15           -> V0..V15
 * Bytes and polynomial coefficients are least-significant first.
 */
`default_nettype none

module lsc1u_core (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       ena,
    input  wire [7:0] rx_data,
    input  wire       rx_valid,
    output wire       rx_ready,
    output wire [7:0] tx_data,
    output wire       tx_valid,
    input  wire       tx_ready,
    output wire       busy,
    output wire       fault,
    output wire       done_pulse
);
    localparam [7:0] CMD_XOR = 8'h01;
    localparam [7:0] CMD_MUL = 8'h02;
    localparam [7:0] CMD_SET = 8'h03;

    localparam [3:0] IDLE     = 4'd0;
    localparam [3:0] XOR_A    = 4'd1;
    localparam [3:0] XOR_B    = 4'd2;
    localparam [3:0] SET_RX   = 4'd3;
    localparam [3:0] MUL_A    = 4'd4;
    localparam [3:0] MUL_B    = 4'd5;
    localparam [3:0] MUL_BITS = 4'd6;
    localparam [3:0] MUL_TX   = 4'd7;

    reg [3:0] state;
    reg [3:0] byte_index;
    reg [7:0] saved_byte;
    reg [7:0] out_byte;
    reg       out_valid;
    reg       fault_reg;
    reg       done_reg;

    wire mul_a_valid = ena && rx_valid && rx_ready && (state == MUL_A);
    wire mul_bit_valid =
        ena && (((state == MUL_B) && rx_valid && rx_ready) ||
                (state == MUL_BITS));
    wire mul_bit_value =
        (state == MUL_B) ? rx_data[0] : saved_byte[0];
    wire mul_tail_last = (saved_byte[7:1] == 7'b0000001);
    wire mul_bit_last =
        (state == MUL_BITS) && (byte_index == 4'd15) && mul_tail_last;
    wire mul_result_shift =
        ena && (state == MUL_TX) && !out_valid;
    wire [7:0] mul_result_byte;

    gf128_mul_bitstream multiplier (
        .clk(clk),
        .rst_n(rst_n),
        .abort(1'b0),
        .a_valid(mul_a_valid),
        .a_byte(rx_data),
        .a_last(byte_index == 4'd15),
        .bit_valid(mul_bit_valid),
        .bit_value(mul_bit_value),
        .bit_last(mul_bit_last),
        .result_shift(mul_result_shift),
        .result_byte(mul_result_byte)
    );

    assign rx_ready = ena && !out_valid &&
        ((state == IDLE) || (state == XOR_A) || (state == XOR_B) ||
         (state == SET_RX) || (state == MUL_A) || (state == MUL_B));
    assign tx_data = out_byte;
    assign tx_valid = ena && out_valid;
    assign busy = ena && ((state != IDLE) || out_valid);
    assign fault = ena && fault_reg;
    assign done_pulse = ena && rst_n && done_reg;

    wire rx_fire = rx_valid && rx_ready;
    wire tx_fire = tx_valid && tx_ready;

    always @(posedge clk) begin
        if (!rst_n) begin
            state      <= IDLE;
            byte_index <= 4'd0;
            saved_byte <= 8'd0;
            out_byte   <= 8'd0;
            out_valid  <= 1'b0;
            fault_reg  <= 1'b0;
            done_reg   <= 1'b0;
        end else if (!ena) begin
            done_reg <= 1'b0;
        end else begin
            done_reg <= 1'b0;

            if (tx_fire)
                out_valid <= 1'b0;

            case (state)
                IDLE: begin
                    byte_index <= 4'd0;
                    if (rx_fire) begin
                        fault_reg <= 1'b0;
                        case (rx_data)
                            CMD_XOR: state <= XOR_A;
                            CMD_MUL: state <= MUL_A;
                            CMD_SET: state <= SET_RX;
                            default: begin
                                out_byte  <= 8'he0;
                                out_valid <= 1'b1;
                                fault_reg <= 1'b1;
                            end
                        endcase
                    end
                    if (tx_fire) begin
                        done_reg <= 1'b1;
                        fault_reg <= 1'b0;
                    end
                end

                XOR_A: if (rx_fire) begin
                    saved_byte <= rx_data;
                    state <= XOR_B;
                end

                XOR_B: if (rx_fire) begin
                    out_byte <= saved_byte ^ rx_data;
                    out_valid <= 1'b1;
                    state <= XOR_A;
                end

                SET_RX: if (rx_fire) begin
                    out_byte <= rx_data;
                    out_valid <= 1'b1;
                end

                MUL_A: if (rx_fire) begin
                    if (byte_index == 4'd15) begin
                        byte_index <= 4'd0;
                        state <= MUL_B;
                    end else begin
                        byte_index <= byte_index + 1'b1;
                    end
                end

                MUL_B: if (rx_fire) begin
                    saved_byte <= {1'b1, rx_data[7:1]};
                    state <= MUL_BITS;
                end

                MUL_BITS: begin
                    if (mul_tail_last) begin
                        if (byte_index == 4'd15) begin
                            byte_index <= 4'd0;
                            state <= MUL_TX;
                        end else begin
                            byte_index <= byte_index + 1'b1;
                            state <= MUL_B;
                        end
                    end else begin
                        saved_byte <= saved_byte >> 1;
                    end
                end

                MUL_TX: if (!out_valid) begin
                    out_byte <= mul_result_byte;
                    out_valid <= 1'b1;
                end

                default: begin
                    state <= IDLE;
                    fault_reg <= 1'b1;
                end
            endcase

            if (tx_fire && (state != IDLE)) begin
                if (byte_index == 4'd15) begin
                    byte_index <= 4'd0;
                    state <= IDLE;
                    done_reg <= 1'b1;
                end else if ((state == XOR_A) || (state == SET_RX) ||
                             (state == MUL_TX)) begin
                    byte_index <= byte_index + 1'b1;
                end
            end
        end
    end
endmodule

`default_nettype wire

`default_nettype none

// Cycle-exact architectural transition model for every accepted LSC-1u
// micro-op.  The concrete multiplier is replaced by gf128_mul_spec_formal;
// gf128_mul_stream_refinement.sby proves that production boundary separately.
module lsc1u_compositional_refinement_formal;
    (* gclk *) reg clk;
    (* anyseq *) reg rst_n, ena, rx_valid, tx_ready;
    (* anyseq *) reg [7:0] rx_data;
    wire rx_ready, tx_valid, busy, fault, done_pulse;
    wire [7:0] tx_data;
    wire [3:0] formal_state, formal_byte_index;
    wire [7:0] formal_saved_byte, formal_out_byte;
    wire formal_out_valid, formal_fault_reg, formal_done_reg;
    wire [127:0] formal_mul_power, formal_mul_product;
    wire formal_mul_a_valid, formal_mul_bit_valid, formal_mul_bit_value;
    wire formal_mul_bit_last, formal_mul_result_shift;

    lsc1u_core dut (.*);

    localparam IDLE=0, XOR_A=1, XOR_B=2, SET_RX=3,
               MUL_A=4, MUL_B=5, MUL_BITS=6, MUL_TX=7;
    reg past_valid = 0;
    reg [3:0] r_state, r_index;
    reg [7:0] r_saved, r_out;
    reg r_valid, r_fault, r_done;
    wire r_rx_ready = ena && !r_valid &&
        (r_state==IDLE || r_state==XOR_A || r_state==XOR_B ||
         r_state==SET_RX || r_state==MUL_A || r_state==MUL_B);
    wire r_tx_valid = ena && r_valid;
    wire r_rx_fire = rx_valid && r_rx_ready;
    wire r_tx_fire = r_tx_valid && tx_ready;
    wire r_busy = ena && (r_state != IDLE || r_valid);
    wire r_tail_last = r_saved[7:1] == 7'b0000001;

    always @(posedge clk) begin
        past_valid <= 1;
        if (!past_valid) assume(!rst_n);

        if (!rst_n) begin
            r_state<=IDLE; r_index<=0; r_saved<=0; r_out<=0;
            r_valid<=0; r_fault<=0; r_done<=0;
        end else if (!ena) begin
            r_done <= 0;
        end else begin
            r_done <= 0;
            if (r_tx_fire) r_valid <= 0;

            case (r_state)
                IDLE: begin
                    r_index <= 0;
                    if (r_rx_fire) begin
                        r_fault <= 0;
                        case (rx_data)
                            8'h01: r_state <= XOR_A;
                            8'h02: r_state <= MUL_A;
                            8'h03: r_state <= SET_RX;
                            default: begin r_out<=8'he0; r_valid<=1; r_fault<=1; end
                        endcase
                    end
                    if (r_tx_fire) begin r_done<=1; r_fault<=0; end
                end
                XOR_A: if (r_rx_fire) begin r_saved<=rx_data; r_state<=XOR_B; end
                XOR_B: if (r_rx_fire) begin
                    r_out<=r_saved^rx_data; r_valid<=1; r_state<=XOR_A;
                end
                SET_RX: if (r_rx_fire) begin r_out<=rx_data; r_valid<=1; end
                MUL_A: if (r_rx_fire) begin
                    if (r_index==15) begin
                        r_index<=0; r_state<=MUL_B;
                    end else r_index<=r_index+1'b1;
                end
                MUL_B: if (r_rx_fire) begin
                    r_saved<={1'b1,rx_data[7:1]}; r_state<=MUL_BITS;
                end
                MUL_BITS: begin
                    if (r_tail_last) begin
                        if (r_index==15) begin r_index<=0; r_state<=MUL_TX; end
                        else begin r_index<=r_index+1'b1; r_state<=MUL_B; end
                    end else r_saved<=r_saved>>1;
                end
                MUL_TX: if (!r_valid) begin
                    r_out<=formal_mul_product[7:0]; r_valid<=1;
                end
                default: begin r_state<=IDLE; r_fault<=1; end
            endcase

            if (r_tx_fire && r_state!=IDLE) begin
                if (r_index==15) begin
                    r_index<=0; r_state<=IDLE; r_done<=1;
                end else if (r_state==XOR_A || r_state==SET_RX || r_state==MUL_TX)
                    r_index<=r_index+1'b1;
            end
        end

        if (past_valid) begin
            assert(rx_ready == r_rx_ready);
            assert(tx_valid == r_tx_valid);
            assert(tx_data == r_out);
            assert(busy == r_busy);
            assert(fault == (ena && r_fault));
            assert(done_pulse == (ena && rst_n && r_done));
            assert(formal_state == r_state);
            assert(formal_byte_index == r_index);
            assert(formal_saved_byte == r_saved);
            assert(formal_out_byte == r_out);
            assert(formal_out_valid == r_valid);
            assert(formal_fault_reg == r_fault);
            assert(formal_done_reg == r_done);
            assert(formal_mul_a_valid ==
                   (ena && rx_valid && r_rx_ready && r_state==MUL_A));
            assert(formal_mul_bit_valid ==
                   (ena && ((r_state==MUL_B && rx_valid && r_rx_ready) ||
                            r_state==MUL_BITS)));
            assert(formal_mul_bit_value ==
                   (r_state==MUL_B ? rx_data[0] : r_saved[0]));
            assert(formal_mul_bit_last ==
                   (r_state==MUL_BITS && r_index==15 && r_tail_last));
            assert(formal_mul_result_shift ==
                   (ena && r_state==MUL_TX && !r_valid));
            assert(r_index < 16);
            if (r_tx_valid && !tx_ready) assert(r_out == tx_data);
        end
    end
endmodule

`default_nettype wire

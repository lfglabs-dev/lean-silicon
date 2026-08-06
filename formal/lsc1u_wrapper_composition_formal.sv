/*
 * Cycle-accurate composition miter for the Tiny Tapeout wrapper.
 *
 * The wrapper instance and a bare reference core receive the same arbitrary
 * pins.  Equality every cycle proves that the wrapper adds neither storage
 * nor latency and therefore preserves every accepted SET/XOR/MUL transaction,
 * including arbitrary source and sink stalls.  The reference core's FORMAL
 * ports are used only to state reset/disable postconditions.
 */
`default_nettype none

module lsc1u_wrapper_composition_formal (
    input wire       clk,
    input wire [7:0] ui_in,
    input wire [7:0] uio_in,
    input wire       ena,
    input wire       rst_n
);
    wire [7:0] wrapped_tx_data;
    wire [7:0] wrapped_uio_out;
    wire [7:0] wrapped_uio_oe;

    tt_um_lfglabs_lsc1u wrapped (
        .ui_in  (ui_in),
        .uo_out (wrapped_tx_data),
        .uio_in (uio_in),
        .uio_out(wrapped_uio_out),
        .uio_oe (wrapped_uio_oe),
        .ena    (ena),
        .clk    (clk),
        .rst_n  (rst_n)
    );

    wire       ref_rx_ready;
    wire [7:0] ref_tx_data;
    wire       ref_tx_valid;
    wire       ref_busy;
    wire       ref_fault;
    wire       ref_done;
    wire [3:0] ref_state;
    wire [3:0] ref_byte_index;
    wire [7:0] ref_saved_byte;
    wire [7:0] ref_out_byte;
    wire       ref_out_valid;
    wire       ref_fault_reg;
    wire       ref_done_reg;
    wire [127:0] ref_mul_power;
    wire [127:0] ref_mul_product;
    wire ref_mul_a_valid, ref_mul_bit_valid, ref_mul_bit_value;
    wire ref_mul_bit_last, ref_mul_result_shift;

    lsc1u_core reference (
        .clk(clk), .rst_n(rst_n), .ena(ena),
        .rx_data(ui_in), .rx_valid(uio_in[0]),
        .rx_ready(ref_rx_ready),
        .tx_data(ref_tx_data), .tx_valid(ref_tx_valid),
        .tx_ready(uio_in[3]),
        .busy(ref_busy), .fault(ref_fault), .done_pulse(ref_done),
        .formal_state(ref_state),
        .formal_byte_index(ref_byte_index),
        .formal_saved_byte(ref_saved_byte),
        .formal_out_byte(ref_out_byte),
        .formal_out_valid(ref_out_valid),
        .formal_fault_reg(ref_fault_reg),
        .formal_done_reg(ref_done_reg),
        .formal_mul_power(ref_mul_power),
        .formal_mul_product(ref_mul_product),
        .formal_mul_a_valid(ref_mul_a_valid),
        .formal_mul_bit_valid(ref_mul_bit_valid),
        .formal_mul_bit_value(ref_mul_bit_value),
        .formal_mul_bit_last(ref_mul_bit_last),
        .formal_mul_result_shift(ref_mul_result_shift)
    );

    reg past_valid = 1'b0;
    always @(posedge clk) begin
        if (!past_valid)
            assume(!rst_n);
        past_valid <= 1'b1;

        /* Exact combinational pin map and output-enable map. */
        if (past_valid) begin
            assert(wrapped_tx_data == (ena ? ref_tx_data : 8'h00));
            assert(wrapped_uio_out == (ena ?
                {ref_done, 1'b0, ref_fault, ref_busy,
                 1'b0, ref_tx_valid, ref_rx_ready, 1'b0} : 8'h00));
            assert(wrapped_uio_oe == (ena ? 8'b10110110 : 8'h00));
        end

        /* Disable masks every output immediately. */
        if (!ena) begin
            assert(wrapped_tx_data == 8'h00);
            assert(wrapped_uio_out == 8'h00);
            assert(wrapped_uio_oe == 8'h00);
        end

        /* rst_n and ena are passed through: either clears retained state. */
        if (past_valid && (!$past(rst_n) || !$past(ena))) begin
            assert(ref_state == 4'd0);
            assert(ref_byte_index == 4'd0);
            assert(ref_saved_byte == 8'd0);
            assert(ref_out_byte == 8'd0);
            assert(!ref_out_valid);
            assert(!ref_fault_reg);
            assert(!ref_done_reg);
            assert(ref_mul_power == 128'd0);
            assert(ref_mul_product == 128'd0);
        end
    end
endmodule

`default_nettype wire

`default_nettype none

/*
 * Cycle-accurate retained-boundary refinement for the LSC-1u XOR micro-op.
 *
 * The environment is free to stall either ready/valid channel, pause ena, or
 * assert reset on any cycle after the required initial reset.  The sole
 * opcode assumption is local to command acceptance: an accepted command in
 * the model's idle state is XOR.  Payload bytes remain completely symbolic.
 *
 * The reference state is intentionally smaller than the implementation: it
 * retains only the phase, lane, first operand, pending result, fault and
 * retirement pulse needed to describe XOR.  The concrete multiplier is cut
 * away because no XOR transition observes it.
 */
module lsc1u_xor_refinement_formal;
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

    localparam [1:0] R_IDLE = 2'd0;
    localparam [1:0] R_A    = 2'd1;
    localparam [1:0] R_B    = 2'd2;

    reg past_valid = 1'b0;
    reg [1:0] ref_phase;
    reg [3:0] ref_lane;
    reg [7:0] ref_a;
    reg [7:0] ref_result;
    reg ref_result_valid;
    reg ref_fault;
    reg ref_retired;

    wire ref_rx_ready = ena && !ref_result_valid;
    wire ref_tx_valid = ena && ref_result_valid;
    wire ref_rx_fire = rx_valid && ref_rx_ready;
    wire ref_tx_fire = ref_tx_valid && tx_ready;
    wire ref_busy = ena && ((ref_phase != R_IDLE) || ref_result_valid);

    always @(posedge clk) begin
        past_valid <= 1'b1;
        if (!past_valid)
            assume(!rst_n);

        // This tranche refines accepted XOR commands, not opcode decode.
        if (rst_n && ref_rx_fire && ref_phase == R_IDLE)
            assume(rx_data == 8'h01);

        if (!rst_n) begin
            ref_phase        <= R_IDLE;
            ref_lane         <= 4'd0;
            ref_a            <= 8'd0;
            ref_result       <= 8'd0;
            ref_result_valid <= 1'b0;
            ref_fault        <= 1'b0;
            ref_retired      <= 1'b0;
        end else if (!ena) begin
            ref_phase        <= R_IDLE;
            ref_lane         <= 4'd0;
            ref_a            <= 8'd0;
            ref_result       <= 8'd0;
            ref_result_valid <= 1'b0;
            ref_fault        <= 1'b0;
            ref_retired      <= 1'b0;
        end else begin
            ref_retired <= 1'b0;

            if (ref_tx_fire)
                ref_result_valid <= 1'b0;

            case (ref_phase)
                R_IDLE: begin
                    ref_lane <= 4'd0;
                    if (ref_rx_fire) begin
                        ref_phase <= R_A;
                        ref_fault <= 1'b0;
                    end
                end
                R_A: if (ref_rx_fire) begin
                    ref_a <= rx_data;
                    ref_phase <= R_B;
                end
                R_B: if (ref_rx_fire) begin
                    ref_result <= ref_a ^ rx_data;
                    ref_result_valid <= 1'b1;
                    ref_phase <= R_A;
                end
                default: ref_phase <= R_IDLE;
            endcase

            if (ref_tx_fire && ref_phase != R_IDLE) begin
                if (ref_lane == 4'd15) begin
                    ref_lane <= 4'd0;
                    ref_phase <= R_IDLE;
                    ref_retired <= 1'b1;
                end else if (ref_phase == R_A) begin
                    ref_lane <= ref_lane + 1'b1;
                end
            end
        end

        if (past_valid) begin
            // Observable refinement relation.
            assert(rx_ready == ref_rx_ready);
            assert(tx_valid == ref_tx_valid);
            assert(tx_data == ref_result);
            assert(busy == ref_busy);
            assert(fault == (ena && ref_fault));
            assert(done_pulse == (ena && rst_n && ref_retired));

            // Inductive invariants of the reduced XOR machine.
            assert(ref_lane < 16);
            assert(ref_phase != R_B || !ref_result_valid);
            assert(!ref_result_valid || ref_phase == R_A);
            if (ref_retired) begin
                assert(ref_phase == R_IDLE);
                assert(!ref_result_valid);
            end
        end
    end
endmodule

`default_nettype wire

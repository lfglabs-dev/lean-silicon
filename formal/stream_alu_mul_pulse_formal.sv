/*
 * Formal check of the multiplier pulse contract on the shipped stream ALU.
 *
 * `asic_core/rtl/gf2n_mul_bitstream.sv` states in prose that "the parent must
 * issue mutually exclusive a_valid, bit_valid, and result_shift pulses", but
 * nothing in the repository asserted it, and the shipped RTL carries no SVA.
 * This file asserts exactly that contract against the production
 * `leanvm_b_stream_alu` FSM without modifying any synthesizable source: the
 * checker is attached with a SystemVerilog `bind`, so the design under proof
 * is the shipped module, byte for byte.
 *
 * Scope: this proves the pulse-exclusivity contract only. It says nothing
 * about GF(2^128) product correctness, opcode decoding, or ISA conformance.
 * See docs/PROOF_BOUNDARIES.md.
 */
`default_nettype none

/*
 * Checker instantiated inside every leanvm_b_stream_alu via `bind` below.
 *
 * `$onehot0` is not supported by every Yosys SystemVerilog frontend, so the
 * property is written in its expanded form. For a three-bit vector,
 *   $onehot0({x,y,z}) === !((x&y) | (x&z) | (y&z))
 * because "at most one bit set" is exactly "no two bits set simultaneously".
 */
module leanvm_b_mul_pulse_check (
    input wire clk,
    input wire rst_n,
    input wire a_valid,
    input wire bit_valid,
    input wire result_shift
);
    wire onehot0_mul_pulses =
        !((a_valid && bit_valid) ||
          (a_valid && result_shift) ||
          (bit_valid && result_shift));

    always @(posedge clk) begin
        if (rst_n) begin
            // The contract documented by gf2n_mul_bitstream.sv.
            assert (onehot0_mul_pulses);

            // Non-vacuity: each pulse must be individually reachable, so the
            // assertion above is not satisfied merely by a dead multiplier
            // interface. These are cover statements, not constraints.
            cover (a_valid);
            cover (bit_valid);
            cover (result_shift);
        end
    end
endmodule

bind leanvm_b_stream_alu leanvm_b_mul_pulse_check u_mul_pulse_check (
    .clk          (clk),
    .rst_n        (rst_n),
    .a_valid      (mul_a_valid),
    .bit_valid    (mul_bit_valid),
    .result_shift (mul_result_shift)
);

/*
 * Proof harness. All stream-side inputs are left free, so the property is
 * proved for every host handshake pattern, including stalls, aborts and
 * illegal opcodes.
 *
 * Environmental assumptions, and nothing else:
 *   - a single synchronous clock;
 *   - rst_n is low for the first cycle and high thereafter, matching the
 *     synchronous active-low reset the RTL implements.
 */
module stream_alu_mul_pulse_formal (
    input wire       clk,
    input wire [7:0] rx_data,
    input wire       rx_valid,
    input wire       tx_ready,
    input wire       abort
);
    reg rst_n = 1'b0;
    always @(posedge clk)
        rst_n <= 1'b1;

    wire       rx_ready;
    wire [7:0] tx_data;
    wire       tx_valid;
    wire       busy;
    wire       done_pulse;
    wire       fault;

    leanvm_b_stream_alu dut (
        .clk        (clk),
        .rst_n      (rst_n),
        .abort      (abort),
        .rx_data    (rx_data),
        .rx_valid   (rx_valid),
        .rx_ready   (rx_ready),
        .tx_data    (tx_data),
        .tx_valid   (tx_valid),
        .tx_ready   (tx_ready),
        .busy       (busy),
        .done_pulse (done_pulse),
        .fault      (fault)
    );
endmodule

`default_nettype wire

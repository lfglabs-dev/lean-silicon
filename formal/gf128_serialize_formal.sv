/*
 * SymbiYosys harness for the WIDTH=128 byte-serialization behaviour of
 * gf2n_mul_bitstream, as instantiated by gf128_mul_bitstream.
 *
 * `formal/gf8_mul_formal.sv` proves the GF(2^8) product, but it ties
 * `a_last` high and `result_shift` low, so it never exercises either
 * 16-beat serialization path.  This harness covers exactly that gap:
 *
 *   - the 16-beat little-endian A operand load, and
 *   - the 16-beat destructive result shift-out,
 *
 * at the production width, over a symbolic 128-bit operand.  The operand is
 * `anyconst`, so a passing run covers all 2^128 operand values; it is not a
 * sampled or randomized check.
 *
 * Multiplication itself is deliberately not the subject here: the harness
 * multiplies by the field identity so that the value travelling through the
 * datapath is the operand itself and any byte-ordering defect is visible.
 * See docs/PROOF_BOUNDARIES.md for what this does and does not establish.
 */
`default_nettype none

module gf128_serialize_formal;
    localparam integer BYTES = 16;

    // Phase encoding (one phase per posedge of the generated clock):
    //   0            reset held low
    //   1  .. 16     A byte load, byte i-1 presented in phase i
    //   17           one multiplier bit, value 1, flagged as last
    //   18 .. 33     result shift-out, byte i-18 expected in phase i
    //   34           terminal, held
    localparam integer PH_LOAD_FIRST  = 1;
    localparam integer PH_LOAD_LAST   = PH_LOAD_FIRST + BYTES - 1;   // 16
    localparam integer PH_BIT         = PH_LOAD_LAST + 1;            // 17
    localparam integer PH_SHIFT_FIRST = PH_BIT + 1;                  // 18
    localparam integer PH_SHIFT_LAST  = PH_SHIFT_FIRST + BYTES - 1;  // 33
    localparam integer PH_DONE        = PH_SHIFT_LAST + 1;           // 34

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg [5:0] phase = 6'd0;

    (* anyconst *) wire [127:0] operand_a;

    always @($global_clock)
        clk <= ~clk;

    wire in_load  = (phase >= PH_LOAD_FIRST)  && (phase <= PH_LOAD_LAST);
    wire in_shift = (phase >= PH_SHIFT_FIRST) && (phase <= PH_SHIFT_LAST);

    // Byte index within whichever 16-beat phase is active.
    wire [3:0] load_index  = phase[3:0] - PH_LOAD_FIRST[3:0];
    wire [3:0] shift_index = phase[3:0] - PH_SHIFT_FIRST[3:0];

    // Little-endian arrival order: byte 0 of the operand arrives first.
    wire [7:0] a_byte = operand_a[{load_index, 3'b000} +: 8];

    // Expected little-endian emission order: byte 0 of the operand leaves first.
    wire [7:0] expected_byte = operand_a[{shift_index, 3'b000} +: 8];

    wire a_valid      = in_load;
    wire a_last       = (phase == PH_LOAD_LAST);
    wire bit_valid    = (phase == PH_BIT);
    wire bit_last     = (phase == PH_BIT);
    wire result_shift = in_shift;

    wire [7:0] result_byte;

    gf128_mul_bitstream dut (
        .clk          (clk),
        .rst_n        (rst_n),
        .abort        (1'b0),
        .a_valid      (a_valid),
        .a_byte       (a_byte),
        .a_last       (a_last),
        // Multiply by the field identity 1: a single multiplier bit whose
        // value is 1 and which is flagged as the last bit, so the datapath
        // performs one conditional XOR into the zeroed accumulator and no
        // multiply-by-x step.  The accumulator therefore holds exactly the
        // loaded A shift register.
        .bit_valid    (bit_valid),
        .bit_value    (1'b1),
        .bit_last     (bit_last),
        .result_shift (result_shift),
        .result_byte  (result_byte)
    );

    always @(posedge clk) begin
        if (phase == 6'd0) begin
            rst_n <= 1'b1;
            phase <= 6'd1;
        end else if (phase < PH_DONE) begin
            phase <= phase + 1'b1;
        end

        // Composed serialization property.  Beat i of the shift-out phase
        // must present operand byte i, for every i in 0..15.  A defect in
        // either the load order or the shift-out order fails this check.
        if (in_shift)
            assert (result_byte == expected_byte);

        // Reachability witness: the final shift-out beat is actually reached,
        // so the assertion above is not vacuously true for lack of a trace.
        if (phase == PH_SHIFT_LAST)
            cover (1'b1);
    end

endmodule

`default_nettype wire

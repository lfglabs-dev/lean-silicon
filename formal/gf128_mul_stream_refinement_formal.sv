`default_nettype none

// Unbounded event-level refinement of the production WIDTH=128 datapath.
// Inputs may pause arbitrarily.  phase assumptions describe the public
// protocol only; byte and bit values and reset/abort timing are unconstrained.
module gf128_mul_stream_refinement_formal;
    (* gclk *) reg clk;
    (* anyseq *) reg rst_n, abort, step;
    (* anyseq *) reg [7:0] stream_data;
    (* anyseq *) reg stream_bit;

    reg past_valid = 0;
    reg [1:0] phase;
    reg [4:0] a_count, out_count;
    reg [7:0] bit_count;
    reg [127:0] spec_a, spec_power, spec_product;

    localparam LOAD = 0, BITS = 1, OUT = 2, DONE = 3;
    wire a_valid = step && phase == LOAD;
    wire bit_valid = step && phase == BITS;
    wire result_shift = step && phase == OUT;
    wire a_last = a_count == 15;
    wire bit_last = bit_count == 127;
    wire [7:0] result_byte;
    wire [127:0] formal_a_shift, formal_accumulator;

    function automatic [127:0] xtime;
        input [127:0] value;
        begin
            xtime = {value[126:0], 1'b0} ^
                    (value[127] ? 128'h87 : 128'h0);
        end
    endfunction

    gf128_mul_bitstream dut (
        .clk(clk), .rst_n(rst_n), .abort(abort),
        .a_valid(a_valid), .a_byte(stream_data), .a_last(a_last),
        .bit_valid(bit_valid), .bit_value(stream_bit), .bit_last(bit_last),
        .result_shift(result_shift), .result_byte(result_byte),
        .formal_a_shift(formal_a_shift),
        .formal_accumulator(formal_accumulator)
    );

    always @(posedge clk) begin
        past_valid <= 1;
        if (!past_valid) assume(!rst_n);
`ifdef COVER
        if (past_valid) begin
            assume(rst_n);
            assume(!abort);
            assume(step);
            assume(stream_data == 0);
            assume(!stream_bit);
        end
`endif

        if (!rst_n || abort) begin
            phase <= LOAD; a_count <= 0; bit_count <= 0; out_count <= 0;
            spec_a <= 0; spec_power <= 0; spec_product <= 0;
        end else begin
            if (a_valid) begin
                spec_a <= {stream_data, spec_a[127:8]};
                if (a_last) begin
                    spec_power <= {stream_data, spec_a[127:8]};
                    spec_product <= 0;
                    phase <= BITS; bit_count <= 0;
                end else a_count <= a_count + 1'b1;
            end else if (bit_valid) begin
                if (stream_bit) spec_product <= spec_product ^ spec_power;
                if (bit_last) begin
                    phase <= OUT; out_count <= 0;
                end else begin
                    spec_power <= xtime(spec_power);
                    bit_count <= bit_count + 1'b1;
                end
            end else if (result_shift) begin
                spec_product <= spec_product >> 8;
                if (out_count == 15) phase <= DONE;
                else out_count <= out_count + 1'b1;
            end
        end

        if (past_valid) begin
            assert(result_byte == spec_product[7:0]);
            assert(formal_accumulator == spec_product);
            if (phase != LOAD) assert(formal_a_shift == spec_power);
            cover(phase == DONE);
        end
    end
endmodule

`default_nettype wire

`default_nettype none
module lsc2_diff_fuzzer_ringbuf (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    input  wire [31:0] seed,
    input  wire [31:0] fault_trigger_val,
    input  wire [7:0]  rd_offset,
    output reg         running,
    output reg         divergence_latched,
    output reg  [7:0]  wr_ptr,
    output reg  [15:0] cycles_run,
    output reg  [63:0] trace_rd_word
);
    (* ram_style = "block" *) reg [63:0] ring_bram [0:511];
    reg [31:0] lfsr;

    // Golden reference vs DUT transition
    wire [31:0] next_lfsr = lfsr + 32'd1;
    wire [31:0] ref_out   = (next_lfsr + 32'h9E3779B9) ^ (next_lfsr >> 3);
    wire [31:0] dut_out   = (next_lfsr == fault_trigger_val) ? (ref_out ^ 32'h0000_0001) : ref_out;

    always @(posedge clk) begin
        if (running && !divergence_latched) begin
            ring_bram[{1'b0, wr_ptr}] <= {next_lfsr, dut_out};
        end
        trace_rd_word <= ring_bram[{1'b0, rd_offset}];
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            running            <= 1'b0;
            divergence_latched <= 1'b0;
            wr_ptr             <= 8'd0;
            cycles_run         <= 16'd0;
            lfsr               <= 32'h1;
        end else begin
            if (start) begin
                running            <= 1'b1;
                divergence_latched <= 1'b0;
                wr_ptr             <= 8'd0;
                cycles_run         <= 16'd0;
                lfsr               <= (seed == 32'd0) ? 32'h1 : seed;
            end else if (running && !divergence_latched) begin
                lfsr       <= next_lfsr;
                wr_ptr     <= wr_ptr + 8'd1;
                cycles_run <= cycles_run + 16'd1;
                if (ref_out != dut_out) begin
                    divergence_latched <= 1'b1;
                    running            <= 1'b0;
                end
            end
        end
    end
endmodule
`default_nettype wire

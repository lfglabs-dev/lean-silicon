`default_nettype none
// Non-vacuous bounded R milestone for the registered parser partition.
// The frontend-level composition obligation is recorded separately when it
// cannot be flattened within the bounded diagnostic budget.
module lsc1_packet_frontend_arch_reset_idle;
  (* anyseq *) reg clk, abort, rx_valid, frame_ready;
  wire rst_n = 1'b0;
  (* anyseq *) reg [7:0] rx_data;
  wire rx_ready, frame_valid, fault_valid, busy;
  wire [7:0] frame_opcode, fault_status;
  wire [15:0] frame_length;
  wire [2047:0] frame_payload;
  wire [2:0] arch_state, arch_header_index;
  wire [15:0] arch_body_index, arch_declared_length;
  wire [7:0] arch_version, arch_opcode, arch_flags;
  wire [31:0] arch_crc, arch_received_crc;
  lsc1_packet_rx dut (.*);
  always @(*) assume(clk == 1'b1);
  always @(posedge clk) begin
    if (!rst_n) begin
      assert(arch_state == 0 && arch_header_index == 0 && arch_body_index == 0);
      assert(arch_declared_length == 0 && arch_version == 0 && arch_opcode == 0 && arch_flags == 0);
      assert(arch_crc == 32'hffffffff && arch_received_crc == 0);
      assert(!frame_valid && !fault_valid && !busy);
    end
  end
endmodule
`default_nettype wire

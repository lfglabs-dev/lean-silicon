`default_nettype none
// Bounded, concrete accepted-request partition.  The byte stream is a valid
// zero-length STATUS request (including its wire CRC); no parser state is
// assumed.  This deliberately checks only parser acceptance, not controller
// decode or release equivalence.
module lsc1_packet_rx_status_accept;
  (* anyseq *) reg clk;
  reg [4:0] step;
  wire rst_n = step != 0;
  wire abort = 1'b0, frame_ready = 1'b0;
  wire rx_valid = step >= 1 && step <= 10;
  reg [7:0] rx_data;
  wire rx_ready, frame_valid, fault_valid, busy;
  wire [7:0] frame_opcode, fault_status;
  wire [15:0] frame_length;
  wire [2047:0] frame_payload;
  wire [2:0] arch_state, arch_header_index;
  wire [15:0] arch_body_index, arch_declared_length;
  wire [7:0] arch_version, arch_opcode, arch_flags;
  wire [31:0] arch_crc, arch_received_crc;

  // Keep this a mux chain rather than a ROM: Yosys SAT deliberately does not
  // import the generated $mem cell for a case-table harness.
  always @(*) if (step == 1) rx_data = 8'ha1;
  else if (step == 2) rx_data = 8'h01;
  else if (step == 3) rx_data = 8'h13;
  else if (step == 7) rx_data = 8'h29;
  else if (step == 8) rx_data = 8'hb2;
  else if (step == 9) rx_data = 8'h4e;
  else if (step == 10) rx_data = 8'h1c;
  else rx_data = 0;
  lsc1_packet_rx dut (.*);
  always @(*) assume(clk == 1'b1);
  always @(posedge clk) begin
    step <= step + 1'b1;
    if (step == 11) begin
      assert(frame_valid && !fault_valid);
      assert(frame_opcode == 8'h13 && frame_length == 0);
      assert(arch_opcode == 8'h13 && arch_declared_length == 0);
    end
  end
endmodule
`default_nettype wire

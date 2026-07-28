`default_nettype none
// Bounded serializer partition for the INFO response selected by STATUS.
// start is concrete and two ready-low cycles exercise backpressure.  The
// response is the zero-payload INFO envelope, whose CRC is E7BF94B.
module lsc1_packet_tx_status_response;
  (* anyseq *) reg clk;
  reg [4:0] step;
  wire rst_n = step != 0;
  wire abort = 1'b0;
  wire start = step == 1;
  wire [7:0] status = 8'h03;
  wire [15:0] payload_length = 0;
  wire [543:0] payload = 0;
  wire tx_ready = !(step == 3 || step == 5);
  wire busy, done_pulse, tx_valid;
  wire [7:0] tx_data;
  wire [31:0] payload_crc;
  wire [15:0] arch_index, arch_length;
  wire [7:0] arch_status;
  wire [543:0] arch_payload;
  wire arch_active, arch_done_pulse;
  wire [31:0] arch_saved_crc, arch_envelope_crc_work, arch_payload_crc_work, arch_payload_crc;
  lsc1_packet_tx dut (.*);
  always @(*) assume(clk == 1'b1);
  always @(posedge clk) begin
    step <= step + 1'b1;
    if (arch_active) begin
      assert(tx_valid && busy && arch_status == 8'h03 && arch_length == 0);
      case (arch_index)
        0: assert(tx_data == 8'h5a); 1: assert(tx_data == 8'h01);
        2: assert(tx_data == 8'h03); 3: assert(tx_data == 0);
        4: assert(tx_data == 0); 5: assert(tx_data == 8'h4b);
        6: assert(tx_data == 8'hf9); 7: assert(tx_data == 8'h7b);
        8: assert(tx_data == 8'h0e); default: assert(1'b0);
      endcase
    end
    if (step == 13) assert(done_pulse && !arch_active && payload_crc == 0);
  end
endmodule
`default_nettype wire

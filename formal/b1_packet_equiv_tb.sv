`timescale 1ns/1ps
`default_nettype none
module b1_packet_equiv_tb;
  reg clk=0, rst_n=0, start=0, tx_ready=0;
  reg [7:0] status=8'h84; reg [15:0] length=2; reg [543:0] payload=0;
  wire busy, done_pulse, tx_valid; wire [7:0] tx_data; wire [31:0] payload_crc;
  reg [7:0] expected [0:10]; integer i;
  lsc1_packet_tx tx(.clk,.rst_n,.abort(1'b0),.start,.status,.payload_length(length),.payload,.busy,.done_pulse,.payload_crc,.tx_data,.tx_valid,.tx_ready);
  always #5 clk=~clk;
  task accept_with_stall;
    input [7:0] want;
    begin
      tx_ready=0; #1; if (!tx_valid || tx_data !== want) $fatal(1,"stall byte mismatch");
      @(negedge clk); if (!tx_valid || tx_data !== want) $fatal(1,"unstable under stall");
      tx_ready=1; @(posedge clk); #1; tx_ready=0;
    end
  endtask
  initial begin
    expected[0]=8'h5a; expected[1]=8'h01; expected[2]=8'h84; expected[3]=8'h02; expected[4]=0;
    expected[5]=8'hde; expected[6]=8'had; expected[7]=8'h3f; expected[8]=8'h53; expected[9]=8'h26; expected[10]=8'h88;
    payload[7:0]=8'hde; payload[15:8]=8'had;
    repeat(2) @(posedge clk); rst_n=1; @(posedge clk); start=1; @(posedge clk); start=0;
    for(i=0;i<11;i=i+1) accept_with_stall(expected[i]);
    if (!done_pulse || busy || payload_crc !== 32'hf605253b) $fatal(1,"completion/CRC mismatch");
    $display("B1_TX_STALL_PASS"); $finish;
  end
endmodule
`default_nettype wire

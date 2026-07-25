`timescale 1ns/1ps
module tb_m2_scalar_controller;
 reg clk=0,rst_n=0,load_valid=0,instr_valid=0,inverse_valid=0; reg [31:0] load_addr,instr_a,instr_b,instr_c; reg [127:0] load_value,instr_imm,inverse_value; reg [2:0] instr_op;
 wire instr_ready,inverse_req,retired,fault; wire [127:0] inverse_operand; wire [31:0] pc,fp;
 leanvm_b_m2_scalar_controller #(.MEM_WORDS(32)) dut(.*);
 always #5 clk=~clk;
 function [127:0] xt(input [127:0] x); xt={x[126:0],1'b0}^{128'h87 & {128{x[127]}}}; endfunction
 function [127:0] enc(input integer n); integer j; reg [127:0] z; begin z=1;for(j=0;j<n;j=j+1)z=xt(z);enc=z;end endfunction
 function [127:0] mul(input [127:0] x,input [127:0] y); integer k; reg [127:0] a,b,z; begin a=x;b=y;z=0;for(k=0;k<128;k=k+1)begin if(b[0])z=z^a;a=xt(a);b=b>>1;end mul=z;end endfunction
 function [127:0] inv(input [127:0] x); integer k; reg [127:0] a,b,z; begin a=x;b=x;z=1; for(k=0;k<128;k=k+1) begin if((((128'hfffffffffffffffffffffffffffffffe)>>k)&1)!=0) z=mul(z,a); a=mul(a,a); end inv=z; end endfunction
 task load; input [31:0] a; input [127:0] v; begin @(negedge clk);load_addr=a;load_value=v;load_valid=1;@(negedge clk);load_valid=0;end endtask
 task issue; input [2:0] op;input[31:0] a,b,c;input[127:0] im; begin @(negedge clk);while(!instr_ready)@(negedge clk);instr_op=op;instr_a=a;instr_b=b;instr_c=c;instr_imm=im;instr_valid=1;@(negedge clk);instr_valid=0;while(!retired && !fault) begin @(negedge clk); if(inverse_req) begin inverse_value=inv(inverse_operand);inverse_valid=1;@(negedge clk);inverse_valid=0;end end end endtask
 initial begin load_addr=0;load_value=0;instr_a=0;instr_b=0;instr_c=0;instr_imm=0;instr_op=0;inverse_value=0; #12;rst_n=1;
   load(0,128'd1); load(1,0); load(2,128'h12); load(3,128'h34); issue(0,2,3,4,0); if(dut.mem[4]!==128'h26)$fatal(1,"xor"); issue(1,2,3,5,0); if(dut.mem[5]!==mul(128'h12,128'h34))$fatal(1,"mul");
   load(6,128'h55); load(8,128'h33); issue(0,6,7,8,0); if(dut.mem[6]!==128'h55 || dut.mem[7]!==128'h66)$fatal(1,"xor backsolve");
   load(9,128'h0a); load(11,mul(128'h0a,128'h05)); issue(1,9,10,11,0); if(dut.mem[9]!==128'h0a || dut.mem[10]!==128'h05 || inverse_req)$fatal(1,"mul backsolve handshake");
   issue(2,12,0,0,128'hdeadbeef); if(dut.mem[12]!==128'hdeadbeef)$fatal(1,"set");
   load(13,1);load(14,enc(6));load(15,enc(4));issue(3,13,14,15,0);if(pc!==6 || fp!==4)$fatal(1,"taken jump");
   issue(2,12,0,0,128'hface);if(dut.mem[16]!==128'hface || dut.mem[12]!==128'hdeadbeef)$fatal(1,"fp-relative set");
   load(20,1);load(21,enc(0));load(22,enc(0));issue(3,16,17,18,0);if(pc!==0 || fp!==0)$fatal(1,"frame restore");
   issue(4,0,0,0,0);if(fault || instr_ready)$fatal(1,"terminal halt");@(negedge clk);if(retired)$fatal(1,"halt retire pulse");
   rst_n=0;@(negedge clk);rst_n=1;load(1,128'h11);load(1,128'h22);if(!fault)$fatal(1,"loader write-once conflict");
   rst_n=0;@(negedge clk);rst_n=1;load(2,128'h0a);load(4,mul(128'h0a,128'h05));
   @(negedge clk);instr_op=1;instr_a=2;instr_b=3;instr_c=4;instr_valid=1;@(negedge clk);instr_valid=0;
   if(!inverse_req)$fatal(1,"inverse request missing");load_addr=5;load_value=128'h99;load_valid=1;@(negedge clk);load_valid=0;if(!fault)$fatal(1,"busy load not rejected");
   $display("PASS m2 scalar controller");$finish; end
endmodule

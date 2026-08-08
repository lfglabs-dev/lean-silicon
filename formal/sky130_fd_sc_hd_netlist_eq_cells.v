// Functional models for the SKY130 HD cells instantiated by the fixed v0.1
// release netlist. Power, filler, antenna, and well-tap behavior is intentionally
// absent: this file models digital logic only and is not a replacement for the
// foundry simulation library.
`default_nettype none
`define PINS input VPWR, VGND, VPB, VNB

module sky130_fd_sc_hd__dfxtp_2(input D, CLK, output reg Q, `PINS);
  always @(posedge CLK) Q <= D;
endmodule
module sky130_fd_sc_hd__conb_1(output HI, LO, `PINS); assign HI=1'b1; assign LO=1'b0; endmodule

`define BUF_CELL(n) module n(input A, output X, `PINS); assign X=A; endmodule
`BUF_CELL(sky130_fd_sc_hd__buf_1)
`BUF_CELL(sky130_fd_sc_hd__buf_2)
`BUF_CELL(sky130_fd_sc_hd__buf_4)
`BUF_CELL(sky130_fd_sc_hd__clkbuf_1)
`BUF_CELL(sky130_fd_sc_hd__clkbuf_2)
`BUF_CELL(sky130_fd_sc_hd__clkbuf_4)
`BUF_CELL(sky130_fd_sc_hd__clkbuf_8)
`BUF_CELL(sky130_fd_sc_hd__clkbuf_16)
`BUF_CELL(sky130_fd_sc_hd__clkdlybuf4s25_1)
`BUF_CELL(sky130_fd_sc_hd__dlygate4sd3_1)
`define INV_CELL(n) module n(input A, output Y, `PINS); assign Y=~A; endmodule
`INV_CELL(sky130_fd_sc_hd__inv_2)
`INV_CELL(sky130_fd_sc_hd__clkinv_2)
`INV_CELL(sky130_fd_sc_hd__clkinvlp_4)

module sky130_fd_sc_hd__mux2_1(input A0,A1,S, output X, `PINS); assign X=S?A1:A0; endmodule
module sky130_fd_sc_hd__and2_2(input A,B, output X, `PINS); assign X=A&B; endmodule
module sky130_fd_sc_hd__and2b_2(input A_N,B, output X, `PINS); assign X=(~A_N)&B; endmodule
module sky130_fd_sc_hd__and3_2(input A,B,C, output X, `PINS); assign X=A&B&C; endmodule
module sky130_fd_sc_hd__and3b_2(input A_N,B,C, output X, `PINS); assign X=(~A_N)&B&C; endmodule
module sky130_fd_sc_hd__and4_2(input A,B,C,D, output X, `PINS); assign X=A&B&C&D; endmodule
module sky130_fd_sc_hd__and4b_2(input A_N,B,C,D, output X, `PINS); assign X=(~A_N)&B&C&D; endmodule
module sky130_fd_sc_hd__and4bb_2(input A_N,B_N,C,D, output X, `PINS); assign X=(~A_N)&(~B_N)&C&D; endmodule
module sky130_fd_sc_hd__or2_2(input A,B, output X, `PINS); assign X=A|B; endmodule
module sky130_fd_sc_hd__or3_2(input A,B,C, output X, `PINS); assign X=A|B|C; endmodule
module sky130_fd_sc_hd__or4_2(input A,B,C,D, output X, `PINS); assign X=A|B|C|D; endmodule
module sky130_fd_sc_hd__or4b_2(input A,B,C,D_N, output X, `PINS); assign X=A|B|C|(~D_N); endmodule
module sky130_fd_sc_hd__nand2_2(input A,B, output Y, `PINS); assign Y=~(A&B); endmodule
module sky130_fd_sc_hd__nand2b_2(input A_N,B, output Y, `PINS); assign Y=~((~A_N)&B); endmodule
module sky130_fd_sc_hd__nand3_2(input A,B,C, output Y, `PINS); assign Y=~(A&B&C); endmodule
module sky130_fd_sc_hd__nand4_2(input A,B,C,D, output Y, `PINS); assign Y=~(A&B&C&D); endmodule
module sky130_fd_sc_hd__nor2_2(input A,B, output Y, `PINS); assign Y=~(A|B); endmodule
module sky130_fd_sc_hd__nor3_2(input A,B,C, output Y, `PINS); assign Y=~(A|B|C); endmodule
module sky130_fd_sc_hd__nor4_2(input A,B,C,D, output Y, `PINS); assign Y=~(A|B|C|D); endmodule
module sky130_fd_sc_hd__nor4b_2(input A,B,C,D_N, output Y, `PINS); assign Y=~(A|B|C|(~D_N)); endmodule
module sky130_fd_sc_hd__nor4_4(input A,B,C,D, output Y, `PINS); assign Y=~(A|B|C|D); endmodule
module sky130_fd_sc_hd__nor4b_4(input A,B,C,D_N, output Y, `PINS); assign Y=~(A|B|C|(~D_N)); endmodule

`define AO21(n,o,e) module n(input A1,A2,B1, output o, `PINS); assign o=e; endmodule
`AO21(sky130_fd_sc_hd__a21o_2,X,(A1&A2)|B1)
`AO21(sky130_fd_sc_hd__a21oi_2,Y,~((A1&A2)|B1))
`define AO211(n,o,e) module n(input A1,A2,B1,C1, output o, `PINS); assign o=e; endmodule
`AO211(sky130_fd_sc_hd__a211o_2,X,(A1&A2)|B1|C1)
`AO211(sky130_fd_sc_hd__a211oi_2,Y,~((A1&A2)|B1|C1))
module sky130_fd_sc_hd__a2111oi_1(input A1,A2,B1,C1,D1, output Y, `PINS); assign Y=~((A1&A2)|B1|C1|D1); endmodule
module sky130_fd_sc_hd__a2111oi_2(input A1,A2,B1,C1,D1, output Y, `PINS); assign Y=~((A1&A2)|B1|C1|D1); endmodule
module sky130_fd_sc_hd__a221o_2(input A1,A2,B1,B2,C1, output X, `PINS); assign X=(A1&A2)|(B1&B2)|C1; endmodule
module sky130_fd_sc_hd__a22o_2(input A1,A2,B1,B2, output X, `PINS); assign X=(A1&A2)|(B1&B2); endmodule
module sky130_fd_sc_hd__a2bb2o_2(input A1_N,A2_N,B1,B2, output X, `PINS); assign X=((~A1_N)&(~A2_N))|(B1&B2); endmodule
module sky130_fd_sc_hd__a311o_2(input A1,A2,A3,B1,C1, output X, `PINS); assign X=(A1&A2&A3)|B1|C1; endmodule
module sky130_fd_sc_hd__a31o_2(input A1,A2,A3,B1, output X, `PINS); assign X=(A1&A2&A3)|B1; endmodule
module sky130_fd_sc_hd__a31oi_2(input A1,A2,A3,B1, output Y, `PINS); assign Y=~((A1&A2&A3)|B1); endmodule
module sky130_fd_sc_hd__a32o_2(input A1,A2,A3,B1,B2, output X, `PINS); assign X=(A1&A2&A3)|(B1&B2); endmodule

`define OA21(n,o,e) module n(input A1,A2,B1, output o, `PINS); assign o=e; endmodule
`OA21(sky130_fd_sc_hd__o21a_2,X,(A1|A2)&B1)
`OA21(sky130_fd_sc_hd__o21ai_2,Y,~((A1|A2)&B1))
`define OA211(n,o,e) module n(input A1,A2,B1,C1, output o, `PINS); assign o=e; endmodule
`OA211(sky130_fd_sc_hd__o211a_2,X,(A1|A2)&B1&C1)
`OA211(sky130_fd_sc_hd__o211ai_2,Y,~((A1|A2)&B1&C1))
module sky130_fd_sc_hd__o2111a_2(input A1,A2,B1,C1,D1, output X, `PINS); assign X=(A1|A2)&B1&C1&D1; endmodule
module sky130_fd_sc_hd__o221a_2(input A1,A2,B1,B2,C1, output X, `PINS); assign X=(A1|A2)&(B1|B2)&C1; endmodule
module sky130_fd_sc_hd__o221ai_2(input A1,A2,B1,B2,C1, output Y, `PINS); assign Y=~((A1|A2)&(B1|B2)&C1); endmodule
module sky130_fd_sc_hd__o22a_2(input A1,A2,B1,B2, output X, `PINS); assign X=(A1|A2)&(B1|B2); endmodule
module sky130_fd_sc_hd__o31a_2(input A1,A2,A3,B1, output X, `PINS); assign X=(A1|A2|A3)&B1; endmodule
module sky130_fd_sc_hd__o31ai_2(input A1,A2,A3,B1, output Y, `PINS); assign Y=~((A1|A2|A3)&B1); endmodule

module sky130_fd_sc_hd__decap_3(`PINS); endmodule
module sky130_fd_sc_hd__fill_1(`PINS); endmodule
module sky130_fd_sc_hd__fill_2(`PINS); endmodule
module sky130_fd_sc_hd__tapvpwrvgnd_1(`PINS); endmodule
module sky130_fd_sc_hd__diode_2(input DIODE, `PINS); endmodule
`default_nettype wire

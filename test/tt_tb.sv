`default_nettype none
`timescale 1ns/1ps

module tt_tb;
    reg clk = 0;
    reg rst_n = 0;
    reg ena = 0;
    reg [7:0] ui_in = 0;
    reg [7:0] uio_in = 0;
    wire [7:0] uo_out;
    wire [7:0] uio_out;
    wire [7:0] uio_oe;
    supply1 VPWR;
    supply0 VGND;

    always #20 clk = ~clk;

`ifdef GL_TEST
    tt_um_lfglabs_lsc1u dut (
        .VPWR(VPWR), .VGND(VGND),
        .ui_in(ui_in), .uo_out(uo_out),
        .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
        .ena(ena), .clk(clk), .rst_n(rst_n)
    );
`else
    tt_um_lfglabs_lsc1u dut (
        .ui_in(ui_in), .uo_out(uo_out),
        .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
        .ena(ena), .clk(clk), .rst_n(rst_n)
    );
`endif
endmodule

`default_nettype wire

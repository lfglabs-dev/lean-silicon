set ::env(DESIGN_NAME) tt_um_leanvm_b_mincore
set ::env(VERILOG_FILES) "\
    $::env(DESIGN_DIR)/gf2n_mul_bitstream.sv \
    $::env(DESIGN_DIR)/gf128_mul_bitstream.sv \
    $::env(DESIGN_DIR)/leanvm_b_stream_alu.sv \
    $::env(DESIGN_DIR)/tt_um_leanvm_b_mincore.sv"
set ::env(CLOCK_PORT) "clk"
set ::env(CLOCK_PERIOD) "40"

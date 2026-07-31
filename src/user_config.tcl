set ::env(DESIGN_NAME) tt_um_lfglabs_lsc1u
set ::env(VERILOG_FILES) "\
    $::env(DESIGN_DIR)/../asic_core/rtl/gf2n_mul_bitstream.sv \
    $::env(DESIGN_DIR)/../asic_core/rtl/gf128_mul_bitstream.sv \
    $::env(DESIGN_DIR)/lsc1u_core.sv \
    $::env(DESIGN_DIR)/tt_um_lfglabs_lsc1u.sv"
set ::env(CLOCK_PORT) "clk"
set ::env(CLOCK_PERIOD) "40"

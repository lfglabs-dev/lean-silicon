PROJECT_SOURCES = \
  ../asic_core/rtl/gf2n_mul_bitstream.sv \
  ../asic_core/rtl/gf128_mul_bitstream.sv \
  ../asic_core/rtl/leanvm_b_stream_alu.sv \
  ../asic_core/rtl/lean_silicon_lsc1.sv

.PHONY: sim clean

sim:
	iverilog -g2012 -Wall -s tb_stream_alu -o tb_stream_alu.vvp $(PROJECT_SOURCES) tb_stream_alu.sv
	vvp tb_stream_alu.vvp

clean:
	rm -f tb_stream_alu.vvp

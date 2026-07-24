PROJECT_SOURCES = \
  ../src/gf2n_mul_bitstream.sv \
  ../src/gf128_mul_bitstream.sv \
  ../src/leanvm_b_stream_alu.sv

.PHONY: sim clean

sim:
	iverilog -g2012 -Wall -s tb_stream_alu -o tb_stream_alu.vvp $(PROJECT_SOURCES) tb_stream_alu.sv
	vvp tb_stream_alu.vvp

clean:
	rm -f tb_stream_alu.vvp

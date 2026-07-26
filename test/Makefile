PROJECT_SOURCES = \
  ../asic_core/rtl/gf2n_mul_bitstream.sv \
  ../asic_core/rtl/gf128_mul_bitstream.sv \
  ../asic_core/rtl/leanvm_b_stream_alu.sv \
  ../asic_core/rtl/lean_silicon_lsc1.sv

.PHONY: sim stream-sim packet-frontend-sim packet-frontend-mutation clean

sim: stream-sim packet-frontend-sim packet-frontend-mutation

stream-sim:
	iverilog -g2012 -Wall -s tb_stream_alu -o tb_stream_alu.vvp $(PROJECT_SOURCES) tb_stream_alu.sv
	vvp tb_stream_alu.vvp

packet-frontend-sim:
	$(MAKE) -C packet_frontend sim

packet-frontend-mutation:
	$(MAKE) -C packet_frontend mutation

clean:
	rm -f tb_stream_alu.vvp
	$(MAKE) -C packet_frontend clean

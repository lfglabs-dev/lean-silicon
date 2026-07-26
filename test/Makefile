PROJECT_SOURCES = \
  ../asic_core/rtl/gf2n_mul_bitstream.sv \
  ../asic_core/rtl/gf128_mul_bitstream.sv \
  ../asic_core/rtl/leanvm_b_stream_alu.sv \
  ../asic_core/rtl/lean_silicon_lsc1.sv

BRIDGE_SOURCES = \
  ../fpga/ulx3s/uart_rx.sv \
  ../fpga/ulx3s/uart_tx.sv \
  ../fpga/ulx3s/uart_bridge.sv

.PHONY: sim stream-alu uart-bridge packet-frontend-sim packet-frontend-mutation clean

sim: stream-alu uart-bridge packet-frontend-sim packet-frontend-mutation

stream-alu:
	iverilog -g2012 -Wall -s tb_stream_alu -o tb_stream_alu.vvp $(PROJECT_SOURCES) tb_stream_alu.sv
	vvp tb_stream_alu.vvp

uart-bridge:
	iverilog -g2012 -Wall -s tb_uart_bridge -o tb_uart_bridge.vvp $(PROJECT_SOURCES) $(BRIDGE_SOURCES) tb_uart_bridge.sv
	vvp tb_uart_bridge.vvp

packet-frontend-sim:
	$(MAKE) -C packet_frontend sim

packet-frontend-mutation:
	$(MAKE) -C packet_frontend mutation

clean:
	rm -f tb_stream_alu.vvp tb_uart_bridge.vvp
	$(MAKE) -C packet_frontend clean

PYTHON ?= python3
.DEFAULT_GOAL := tt-test

PROJECT_SOURCES = \
  ../asic_core/rtl/gf2n_mul_bitstream.sv \
  ../asic_core/rtl/gf128_mul_bitstream.sv \
  ../asic_core/rtl/leanvm_b_stream_alu.sv \
  ../asic_core/rtl/lsc1_packet_rx.sv \
  ../asic_core/rtl/lsc1_packet_tx.sv \
  ../asic_core/rtl/lsc1_response_payload_mux.sv \
  ../asic_core/rtl/lsc1_blake3_lifecycle.sv \
  ../asic_core/rtl/lsc1_stream_adapter.sv \
  ../asic_core/rtl/lsc1_field_encoder.sv \
  ../asic_core/rtl/lsc1_packet_frontend.sv \
  ../asic_core/rtl/lean_silicon_lsc1_mincore.sv \
  ../asic_core/rtl/lean_silicon_lsc1.sv

BRIDGE_SOURCES = \
  ../fpga/ulx3s/uart_rx.sv \
  ../fpga/ulx3s/uart_tx.sv \
  ../fpga/ulx3s/uart_bridge.sv

.PHONY: tt-test sim stream-alu uart-bridge packet-uart-bridge packet-frontend-sim packet-frontend-mutation packet-rtl-differential clean

# Default target used by TinyTapeout/tt-gds-action/gl_test@ttsky26c.
# The legacy repository regression remains available explicitly as `make sim`.
tt-test:
	$(MAKE) -f Makefile.tt

sim: stream-alu uart-bridge packet-uart-bridge packet-frontend-sim packet-frontend-mutation packet-rtl-differential

stream-alu:
	iverilog -g2012 -Wall -s tb_stream_alu -o tb_stream_alu.vvp $(PROJECT_SOURCES) tb_stream_alu.sv
	vvp tb_stream_alu.vvp

uart-bridge:
	iverilog -g2012 -Wall -s tb_uart_bridge -o tb_uart_bridge.vvp $(PROJECT_SOURCES) $(BRIDGE_SOURCES) tb_uart_bridge.sv
	vvp tb_uart_bridge.vvp

packet-uart-bridge:
	iverilog -g2012 -Wall -s tb_packet_uart_bridge -o tb_packet_uart_bridge.vvp $(PROJECT_SOURCES) $(BRIDGE_SOURCES) tb_packet_uart_bridge.sv
	vvp tb_packet_uart_bridge.vvp

packet-frontend-sim:
	$(MAKE) -C packet_frontend sim

packet-frontend-mutation:
	$(MAKE) -C packet_frontend mutation
	$(MAKE) -C packet_frontend lifecycle-mutation

packet-rtl-differential:
	cd .. && $(PYTHON) -m unittest sim.test_packet_frontend_rtl_differential -v
	cd .. && PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest -v sim.test_conformance_v3_rtl_differential

clean:
	$(MAKE) -f Makefile.tt clean
	rm -f tb_stream_alu.vvp tb_uart_bridge.vvp tb_packet_uart_bridge.vvp
	$(MAKE) -C packet_frontend clean

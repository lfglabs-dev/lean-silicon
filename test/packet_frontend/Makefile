RTL = ../../asic_core/rtl/lsc1_packet_rx.sv \
      ../../asic_core/rtl/lsc1_packet_tx.sv \
      ../../asic_core/rtl/lsc1_gf128_mul.sv \
      ../../asic_core/rtl/lsc1_packet_frontend.sv

.PHONY: sim mutation clean

sim:
	iverilog -g2012 -Wall -s tb_lsc1_packet_frontend -o tb_lsc1_packet_frontend.vvp $(RTL) tb_lsc1_packet_frontend.sv
	vvp tb_lsc1_packet_frontend.vvp

mutation:
	@d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  sed "s/response\\[22\\] !== 8'hff/response[22] !== 8'hfe/" \
	    tb_lsc1_packet_frontend.sv > "$$d/tb_mut.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/mut.vvp" \
	    $(RTL) "$$d/tb_mut.sv"; \
	  if vvp "$$d/mut.vvp" >"$$d/out" 2>&1; then \
	    echo "mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -q "XOR result payload mismatch" "$$d/out"; \
	  echo "PASS: expected-value mutation was detected"

clean:
	rm -f tb_lsc1_packet_frontend.vvp

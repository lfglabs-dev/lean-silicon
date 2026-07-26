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
	  cp $(RTL) "$$d/"; \
	  sed -i 's/ || tx_start ||/ ||/' "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/busy.vvp" \
	    "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/busy.vvp" >"$$d/busy.out" 2>&1; then \
	    echo "queued-response BUSY mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -q "BUSY dropped while a response was queued" "$$d/busy.out"; \
	  cp ../../asic_core/rtl/lsc1_packet_frontend.sv "$$d/lsc1_packet_frontend.sv"; \
	  sed -i 's/write_value = result_value;/write_value = 0;/' "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/set.vvp" \
	    "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/set.vvp" >"$$d/set.out" 2>&1; then \
	    echo "SET write-value mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -q "SET result write value mismatch" "$$d/set.out"; \
	  cp ../../asic_core/rtl/lsc1_packet_frontend.sv "$$d/lsc1_packet_frontend.sv"; \
	  sed -i 's/txn_id != staged_txn_id ||/1'"'"'b0 ||/' "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/txn.vvp" \
	    "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/txn.vvp" >"$$d/txn.out" 2>&1; then \
	    echo "RETIRE transaction-ID mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -q "status got=02 expected=92" "$$d/txn.out"; \
	  echo "PASS: queued BUSY, SET value, and RETIRE transaction-ID mutations were detected"

clean:
	rm -f tb_lsc1_packet_frontend.vvp

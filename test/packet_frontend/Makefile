PYTHON ?= python3

RTL = ../../asic_core/rtl/lsc1_packet_rx.sv \
      ../../asic_core/rtl/lsc1_packet_tx.sv \
      ../../asic_core/rtl/gf2n_mul_bitstream.sv \
      ../../asic_core/rtl/gf128_mul_bitstream.sv \
      ../../asic_core/rtl/leanvm_b_stream_alu.sv \
      ../../asic_core/rtl/lsc1_stream_adapter.sv \
      ../../asic_core/rtl/lsc1_field_encoder.sv \
      ../../asic_core/rtl/lsc1_packet_frontend.sv

.PHONY: sim mutation differential-mutation clean

sim:
	iverilog -g2012 -Wall -s tb_lsc1_packet_frontend -o tb_lsc1_packet_frontend.vvp $(RTL) tb_lsc1_packet_frontend.sv
	vvp tb_lsc1_packet_frontend.vvp
	iverilog -g2012 -Wall -s tb_deref_retire_trace -o tb_deref_retire_trace.vvp $(RTL) tb_deref_retire_trace.sv
	vvp tb_deref_retire_trace.vvp
	iverilog -g2012 -Wall -s tb_jump_retire_trace -o tb_jump_retire_trace.vvp $(RTL) tb_jump_retire_trace.sv
	vvp tb_jump_retire_trace.vvp
	iverilog -g2012 -Wall -s tb_scalar_retire_trace -o tb_scalar_retire_trace.vvp $(RTL) tb_scalar_retire_trace.sv
	vvp tb_scalar_retire_trace.vvp

mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  cp $(RTL) "$$d/"; \
	  sed -i.bak 's/ || tx_start ||/ ||/' "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/busy.vvp" \
	    "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/busy.vvp" >"$$d/busy.out" 2>&1; then \
	    echo "queued-response BUSY mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -q "BUSY dropped while a response was queued" "$$d/busy.out"; \
	  cp ../../asic_core/rtl/lsc1_packet_frontend.sv "$$d/lsc1_packet_frontend.sv"; \
	  sed -i.bak 's/write_value = result_value;/write_value = 0;/' "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/set.vvp" \
	    "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/set.vvp" >"$$d/set.out" 2>&1; then \
	    echo "SET write-value mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -q "SET result write value mismatch" "$$d/set.out"; \
	  cp ../../asic_core/rtl/lsc1_packet_frontend.sv "$$d/lsc1_packet_frontend.sv"; \
	  sed -i.bak 's/txn_id != staged_txn_id ||/1'"'"'b0 ||/' "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/txn.vvp" \
	    "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/txn.vvp" >"$$d/txn.out" 2>&1; then \
	    echo "RETIRE transaction-ID mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -q "status got=02 expected=92" "$$d/txn.out"; \
	  cp ../../asic_core/rtl/lsc1_packet_frontend.sv "$$d/lsc1_packet_frontend.sv"; \
	  sed -i.bak "/end else if (abort) begin/,/end else begin/ s/result_pending <= 1'b0;/result_pending <= 1'b1;/" \
	    "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/abort.vvp" \
	    "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/abort.vvp" >"$$d/abort.out" 2>&1; then \
	    echo "ABORT-discard mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -q "ABORT emitted a response for a partial packet" "$$d/abort.out"; \
	  cp ../../asic_core/rtl/lsc1_packet_frontend.sv "$$d/lsc1_packet_frontend.sv"; \
	  sed -i.bak "s/frame_opcode == OP_SET && frame_length != 51/1'b0 \\&\\& frame_opcode == OP_SET \\&\\& frame_length != 51/" \
	    "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/length.vvp" \
	    "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/length.vvp" >"$$d/length.out" 2>&1; then \
	    echo "BAD_LENGTH-order mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -q "status got=87 expected=83" "$$d/length.out"; \
	  echo "PASS: BUSY, SET value, RETIRE ID, ABORT, and length-order mutations were detected"

differential-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  cp $(RTL) "$$d/"; \
	  sed -i.bak 's/body_index < MAX_PAYLOAD/body_index < 16'"'"'d94/' "$$d/lsc1_packet_rx.sv"; \
	  if PYTHONPATH=../.. LSC1_RTL_DIR="$$d" $(PYTHON) -m unittest sim.test_packet_frontend_rtl_differential.PacketFrontendRtlDifferentialTests.test_adversarial_jump_inverse_and_xor_backsolve_match_model >"$$d/jump.out" 2>&1; then \
	    echo "JUMP inverse payload-bound mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -q "AssertionError" "$$d/jump.out"; \
	  cp ../../asic_core/rtl/lsc1_packet_rx.sv "$$d/lsc1_packet_rx.sv"; \
	  cp ../../asic_core/rtl/lsc1_packet_frontend.sv "$$d/lsc1_packet_frontend.sv"; \
	  sed -i.bak 's/decision_ok && !decision_deferred && frame_opcode == OP_XOR/decision_ok \&\& frame_opcode == OP_XOR/' "$$d/lsc1_packet_frontend.sv"; \
	  if PYTHONPATH=../.. LSC1_RTL_DIR="$$d" $(PYTHON) -m unittest sim.test_packet_frontend_rtl_differential.PacketFrontendRtlDifferentialTests.test_adversarial_jump_inverse_and_xor_backsolve_match_model >"$$d/xor.out" 2>&1; then \
	    echo "XOR deferred-decision mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -q "AssertionError" "$$d/xor.out"; \
	  echo "PASS: JUMP inverse-width and XOR deferred-decision mutations were detected"

clean:
	rm -f tb_lsc1_packet_frontend.vvp tb_deref_retire_trace.vvp tb_jump_retire_trace.vvp tb_scalar_retire_trace.vvp

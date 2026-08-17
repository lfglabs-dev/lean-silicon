PYTHON ?= python3

RTL = ../../asic_core/rtl/lsc1_packet_rx.sv \
      ../../asic_core/rtl/lsc1_packet_tx.sv \
      ../../asic_core/rtl/lsc1_blake3_lifecycle.sv \
      ../../asic_core/rtl/gf2n_mul_bitstream.sv \
      ../../asic_core/rtl/gf128_mul_bitstream.sv \
      ../../asic_core/rtl/leanvm_b_stream_alu.sv \
      ../../asic_core/rtl/lsc1_stream_adapter.sv \
      ../../asic_core/rtl/lsc1_field_encoder.sv \
      ../../asic_core/rtl/lsc1_packet_frontend.sv

.PHONY: sim transport lifecycle lifecycle-mutation blake3-retire-commit mutation differential-mutation scalar-result-mutation short-response-mutation clean

sim:
	$(MAKE) lifecycle
	$(MAKE) blake3-retire-commit
	$(MAKE) transport
	iverilog -g2012 -Wall -s tb_lsc1_packet_frontend -o tb_lsc1_packet_frontend.vvp $(RTL) tb_lsc1_packet_frontend.sv
	vvp tb_lsc1_packet_frontend.vvp
	iverilog -g2012 -Wall -s tb_deref_retire_trace -o tb_deref_retire_trace.vvp $(RTL) tb_deref_retire_trace.sv
	vvp tb_deref_retire_trace.vvp
	iverilog -g2012 -Wall -s tb_jump_retire_trace -o tb_jump_retire_trace.vvp $(RTL) tb_jump_retire_trace.sv
	vvp tb_jump_retire_trace.vvp
	iverilog -g2012 -Wall -s tb_scalar_retire_trace -o tb_scalar_retire_trace.vvp $(RTL) tb_scalar_retire_trace.sv
	vvp tb_scalar_retire_trace.vvp

transport:
	iverilog -g2012 -Wall -s tb_lsc1_packet_tx_service_required -o tb_lsc1_packet_tx_service_required.vvp \
	  ../../asic_core/rtl/lsc1_packet_tx.sv tb_lsc1_packet_tx_service_required.sv
	vvp tb_lsc1_packet_tx_service_required.vvp

lifecycle:
	iverilog -g2012 -Wall -s tb_lsc1_blake3_lifecycle -o tb_lsc1_blake3_lifecycle.vvp \
	  ../../asic_core/rtl/lsc1_blake3_lifecycle.sv tb_lsc1_blake3_lifecycle.sv
	vvp tb_lsc1_blake3_lifecycle.vvp

blake3-retire-commit:
	iverilog -g2012 -Wall -s tb_blake3_retire_commit -o tb_blake3_retire_commit.vvp \
	  $(RTL) tb_blake3_retire_commit.sv
	vvp tb_blake3_retire_commit.vvp

lifecycle-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  cp ../../asic_core/rtl/lsc1_blake3_lifecycle.sv "$$d/dut.sv"; \
	  for mutation in id done abort; do \
	    cp ../../asic_core/rtl/lsc1_blake3_lifecycle.sv "$$d/dut.sv"; \
	    case $$mutation in \
	      id) sed -i 's/retire_txn_id == staged_txn_id/retire_txn_id != staged_txn_id/' "$$d/dut.sv" ;; \
	  done) sed -i "s/done_pulse <= 1'b1;/done_pulse <= 1'b0;/" "$$d/dut.sv" ;; \
	      abort) sed -i "/end else if (abort) begin/,/end else begin/ s/service_pending <= 1'b0;/service_pending <= 1'b1;/" "$$d/dut.sv" ;; \
	    esac; \
	    iverilog -g2012 -s tb_lsc1_blake3_lifecycle -o "$$d/$$mutation.vvp" "$$d/dut.sv" tb_lsc1_blake3_lifecycle.sv; \
	    if vvp "$$d/$$mutation.vvp" >"$$d/$$mutation.out" 2>&1; then \
	      echo "lifecycle $$mutation mutation unexpectedly survived" >&2; exit 1; \
	    fi; \
	  done; \
	  rm "$$d/dut.sv"; \
	  cp $(RTL) "$$d/"; \
	  sed -i 's/assign blake_retire_attempt = frame_valid/assign blake_retire_attempt = 1'"'"'b0 \&\& frame_valid/' \
	    "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_blake3_retire_commit -o "$$d/commit.vvp" \
	    "$$d"/*.sv tb_blake3_retire_commit.sv; \
	  if vvp "$$d/commit.vvp" >"$$d/commit.out" 2>&1; then \
	    echo "RETIRE commit-edge mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -q "FATAL:" "$$d/commit.out"; \
	  echo "PASS: lifecycle ID, exactly-once done, abort, and commit-edge mutations detected"

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
	  grep -Eq "staged write byte zero|SET result write value mismatch" "$$d/set.out"; \
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
	$(MAKE) scalar-result-mutation
	$(MAKE) short-response-mutation

short-response-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  for mutation in fault_detail status_snapshot retire_offset length unstable_source; do \
	    rm -f "$$d"/*.sv; cp ../../asic_core/rtl/*.sv "$$d/"; \
	    test "$$(grep -Foc '4: tx_payload_external_data = short_detail;' "$$d/lsc1_packet_frontend.sv")" -eq 1; \
	    test "$$(grep -Foc 'short_detail <= last_status;' "$$d/lsc1_packet_frontend.sv")" -eq 1; \
	    test "$$(grep -Foc '8: tx_payload_external_data = committed_pc[7:0];' "$$d/lsc1_packet_frontend.sv")" -eq 1; \
	    test "$$(grep -Foc "tx_length <= 16'd16;" "$$d/lsc1_packet_frontend.sv")" -eq 1; \
	    test "$$(grep -Foc '0: tx_payload_external_data = short_txn_id[0 +: 8];' "$$d/lsc1_packet_frontend.sv")" -eq 1; \
	    case $$mutation in \
	      fault_detail) sed -i 's/4: tx_payload_external_data = short_detail;/4: tx_payload_external_data = short_txn_id[7:0];/' "$$d/lsc1_packet_frontend.sv" ;; \
	      status_snapshot) sed -i 's/short_detail <= last_status;/short_detail <= INFO;/' "$$d/lsc1_packet_frontend.sv" ;; \
	      retire_offset) sed -i 's/8: tx_payload_external_data = committed_pc\[7:0\];/8: tx_payload_external_data = committed_fp[7:0];/' "$$d/lsc1_packet_frontend.sv" ;; \
	      length) sed -i "s/tx_length <= 16'd16;/tx_length <= 16'd15;/" "$$d/lsc1_packet_frontend.sv" ;; \
	      unstable_source) sed -i 's/0: tx_payload_external_data = short_txn_id\[0 +: 8\];/0: tx_payload_external_data = txn_id[7:0];/' "$$d/lsc1_packet_frontend.sv" ;; \
	    esac; \
	    if PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=../.. LSC1_RTL_DIR="$$d" $(PYTHON) -m unittest sim.test_packet_frontend_rtl_differential >"$$d/$$mutation.out" 2>&1; then \
	      echo "short-response $$mutation mutation unexpectedly survived" >&2; exit 1; \
	    fi; \
	    grep -Eq 'FAILED|AssertionError' "$$d/$$mutation.out"; \
	    echo "short-response $$mutation mutant: compile_elaboration=PASS expected_behavioral_kill=PASS"; \
	  done; \
	  echo "PASS: FAULT detail, STATUS snapshot, RETIRE offset/length, and stable-source mutations detected"

scalar-result-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  cp $(RTL) "$$d/"; \
	  test "$$(grep -Fxc '                            17: tx_payload_external_data = scalar_staged_write_value[7:0];' "$$d/lsc1_packet_frontend.sv")" -eq 1; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/baseline.vvp" "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  vvp "$$d/baseline.vvp" >"$$d/baseline.out" 2>&1; \
	  echo "scalar-result baseline: anchor_exactly_once=PASS compile_elaboration=PASS behavior=PASS"; \
	  cp $(RTL) "$$d/"; \
	  test "$$(grep -Foc '17: tx_payload_external_data = scalar_staged_write_value[7:0];' "$$d/lsc1_packet_frontend.sv")" -eq 1; \
	  sed -i 's/17: tx_payload_external_data = scalar_staged_write_value\[7:0\];/17: tx_payload_external_data = scalar_staged_write_value[15:8];/' "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/byte.vvp" "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/byte.vvp" >"$$d/byte.out" 2>&1; then echo "scalar byte-selection mutation unexpectedly survived" >&2; exit 1; fi; \
	  grep -Eq "staged write byte zero|SET result write value mismatch" "$$d/byte.out"; \
	  echo "scalar byte-selection mutant: compile_elaboration=PASS expected_behavioral_kill=PASS"; \
	  cp ../../asic_core/rtl/lsc1_packet_frontend.sv "$$d/lsc1_packet_frontend.sv"; \
	  test "$$(grep -Foc 'result_length = 39;' "$$d/lsc1_packet_frontend.sv")" -eq 1; \
	  sed -i 's/result_length = 39;/result_length = 38;/' "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/length.vvp" "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/length.vvp" >"$$d/length.out" 2>&1; then echo "scalar RESULT-length mutation unexpectedly survived" >&2; exit 1; fi; \
	  grep -q "SET result payload schema mismatch" "$$d/length.out"; \
	  echo "scalar length mutant: compile_elaboration=PASS expected_behavioral_kill=PASS"; \
	  cp ../../asic_core/rtl/lsc1_packet_frontend.sv "$$d/lsc1_packet_frontend.sv"; \
	  test "$$(grep -Foc '17: tx_payload_external_data = scalar_staged_write_value[7:0];' "$$d/lsc1_packet_frontend.sv")" -eq 1; \
	  sed -i 's/17: tx_payload_external_data = scalar_staged_write_value\[7:0\];/17: tx_payload_external_data = write_value[7:0];/' "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/staging.vvp" "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/staging.vvp" >"$$d/staging.out" 2>&1; then echo "scalar stable-staging mutation unexpectedly survived" >&2; exit 1; fi; \
	  grep -q "scalar staged-byte/backpressure stability failed" "$$d/staging.out"; \
	  echo "scalar stable-staging mutant: compile_elaboration=PASS expected_behavioral_kill=PASS"; \
	  echo "PASS: scalar RESULT byte selection, length, CRC/stall, and stable-staging mutations detected"

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
	rm -f tb_lsc1_packet_frontend.vvp tb_lsc1_packet_tx_service_required.vvp tb_lsc1_blake3_lifecycle.vvp tb_blake3_retire_commit.vvp tb_deref_retire_trace.vvp tb_jump_retire_trace.vvp tb_scalar_retire_trace.vvp

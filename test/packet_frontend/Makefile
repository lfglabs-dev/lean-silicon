PYTHON ?= python3

RTL = ../../asic_core/rtl/lsc1_packet_rx.sv \
      ../../asic_core/rtl/lsc1_packet_tx.sv \
      ../../asic_core/rtl/lsc1_response_payload_mux.sv \
      ../../asic_core/rtl/lsc1_blake3_lifecycle.sv \
      ../../asic_core/rtl/gf2n_mul_bitstream.sv \
      ../../asic_core/rtl/gf128_mul_bitstream.sv \
      ../../asic_core/rtl/leanvm_b_stream_alu.sv \
      ../../asic_core/rtl/lsc1_stream_adapter.sv \
      ../../asic_core/rtl/lsc1_field_encoder.sv \
      ../../asic_core/rtl/lsc1_packet_frontend.sv

.PHONY: sim transport response-payload-mux response-payload-mux-mutation serializer-structure serializer-interface-mutation lifecycle lifecycle-mutation blake3-retire-commit mutation differential-mutation scalar-result-mutation short-response-mutation rx-payload-prefix rx-payload-prefix-mutation clean

response-payload-mux:
	iverilog -g2012 -Wall -s tb_lsc1_response_payload_mux -o tb_lsc1_response_payload_mux.vvp \
	  ../../asic_core/rtl/lsc1_response_payload_mux.sv tb_lsc1_response_payload_mux.sv
	vvp tb_lsc1_response_payload_mux.vvp

response-payload-mux-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  for mutation in service result scalar fault status negotiate retired; do \
	    cp ../../asic_core/rtl/lsc1_response_payload_mux.sv "$$d/dut.sv"; \
	    case $$mutation in \
	      service) sed -i 's/blake_staged_service_id\[(payload_index-4)\*8 +: 8\]/blake_staged_txn_id[(payload_index-4)*8 +: 8]/' "$$d/dut.sv" ;; \
	      result) sed -i 's/staged_write_address\[ext_word\]/staged_write_address[0]/' "$$d/dut.sv" ;; \
	      scalar) sed -i 's/17: payload_data = scalar_staged_write_value\[7:0\];/17: payload_data = scalar_staged_write_value[15:8];/' "$$d/dut.sv" ;; \
	      fault) sed -i 's/4: payload_data = short_detail;/4: payload_data = last_fault;/' "$$d/dut.sv" ;; \
	      status) sed -i 's/10: payload_data = last_fault;/10: payload_data = short_detail;/' "$$d/dut.sv" ;; \
	      negotiate) sed -i "s/10: payload_data = 8'h31;/10: payload_data = 8'h30;/" "$$d/dut.sv" ;; \
	      retired) sed -i 's/8: payload_data = committed_pc\[7:0\];/8: payload_data = committed_fp[7:0];/' "$$d/dut.sv" ;; \
	    esac; \
	    iverilog -g2012 -s tb_lsc1_response_payload_mux -o "$$d/$$mutation.vvp" "$$d/dut.sv" tb_lsc1_response_payload_mux.sv; \
	    if vvp "$$d/$$mutation.vvp" >"$$d/$$mutation.out" 2>&1; then echo "response-payload $$mutation mutation unexpectedly survived" >&2; exit 1; fi; \
	    grep -q 'FATAL:' "$$d/$$mutation.out"; \
	    echo "response-payload $$mutation mutant: compile_elaboration=PASS expected_behavioral_kill=PASS"; \
	  done; \
	  echo "PASS: seven response-schema byte-selection mutations behaviorally killed"

sim:
	$(MAKE) serializer-structure
	$(MAKE) rx-payload-prefix
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

serializer-structure:
	@set -e; tx=../../asic_core/rtl/lsc1_packet_tx.sv; fe=../../asic_core/rtl/lsc1_packet_frontend.sv; \
	  inline_reg=saved_; inline_reg=$${inline_reg}payload; mode_reg=saved_; mode_reg=$${mode_reg}external; mode_port=payload_; mode_port=$${mode_port}external; \
	  ! grep -Eq "$$inline_reg|$$mode_reg|input[[:space:]]+wire[[:space:]]+\\[159:0\\][[:space:]]+payload|input[[:space:]]+wire[[:space:]]+$$mode_port([,[:space:]]|$$)" "$$tx"; \
	  awk '/tx_external_kind <= [1-7];/{kind=NR; value=$$3; sub(/;/,"",value); seen[value]=1} /tx_start <= 1.b1;/{if (!kind || NR-kind != 1) exit 1; kind=0} END{for (i=1;i<=7;i++) if (!seen[i]) exit 1; if (length(seen) != 7) exit 1}' "$$fe"; \
	  echo "PASS: external-only serializer structure and kinds 1--7 tx_start paths"

serializer-interface-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  cp ../../asic_core/rtl/lsc1_packet_tx.sv "$$d/dut.sv"; \
	  test "$$(grep -Foc 'tx_data = payload_external_data;' "$$d/dut.sv")" -eq 1; \
	  sed -i 's/tx_data = payload_external_data;/tx_data = payload_external_data ^ 8'"'"'h01;/' "$$d/dut.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_tx_service_required -o "$$d/mutation.vvp" \
	    "$$d/dut.sv" tb_lsc1_packet_tx_service_required.sv; \
	  if vvp "$$d/mutation.vvp" >"$$d/mutation.out" 2>&1; then \
	    echo "serializer external-byte mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -q "SERVICE_REQUIRED payload mismatch" "$$d/mutation.out"; \
	  echo "PASS: serializer external-byte mutant compile/elaboration and behavioral kill"

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
	  cp ../../asic_core/rtl/lsc1_response_payload_mux.sv "$$d/lsc1_response_payload_mux.sv"; \
	  sed -i.bak 's/write_value = result_value;/write_value = 0;/' "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/set.vvp" \
	    "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/set.vvp" >"$$d/set.out" 2>&1; then \
	    echo "SET write-value mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -Eq "staged write byte zero|SET result write value mismatch" "$$d/set.out"; \
	  cp ../../asic_core/rtl/lsc1_packet_frontend.sv "$$d/lsc1_packet_frontend.sv"; \
	  cp ../../asic_core/rtl/lsc1_response_payload_mux.sv "$$d/lsc1_response_payload_mux.sv"; \
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
	$(MAKE) serializer-interface-mutation

short-response-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  for mutation in fault_detail status_snapshot retire_offset length unstable_source; do \
	    rm -f "$$d"/*.sv; cp ../../asic_core/rtl/*.sv "$$d/"; \
	    test "$$(grep -Foc '4: payload_data = short_detail;' "$$d/lsc1_response_payload_mux.sv")" -eq 1; \
	    test "$$(grep -Foc 'short_detail <= last_status;' "$$d/lsc1_packet_frontend.sv")" -eq 1; \
	    test "$$(grep -Foc '8: payload_data = committed_pc[7:0];' "$$d/lsc1_response_payload_mux.sv")" -eq 1; \
	    test "$$(grep -Foc "tx_length <= 16'd16;" "$$d/lsc1_packet_frontend.sv")" -eq 1; \
	    test "$$(grep -Foc '0: payload_data = short_txn_id[0 +: 8];' "$$d/lsc1_response_payload_mux.sv")" -eq 1; \
	    case $$mutation in \
	      fault_detail) sed -i 's/4: payload_data = short_detail;/4: payload_data = short_txn_id[7:0];/' "$$d/lsc1_response_payload_mux.sv" ;; \
	      status_snapshot) sed -i 's/short_detail <= last_status;/short_detail <= INFO;/' "$$d/lsc1_packet_frontend.sv" ;; \
	      retire_offset) sed -i 's/8: payload_data = committed_pc\[7:0\];/8: payload_data = committed_fp[7:0];/' "$$d/lsc1_response_payload_mux.sv" ;; \
	      length) sed -i "s/tx_length <= 16'd16;/tx_length <= 16'd15;/" "$$d/lsc1_packet_frontend.sv" ;; \
	      unstable_source) sed -i 's/0: payload_data = short_txn_id\[0 +: 8\];/0: payload_data = staged_txn_id[7:0];/' "$$d/lsc1_response_payload_mux.sv" ;; \
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
	  test "$$(grep -Fxc '                            17: payload_data = scalar_staged_write_value[7:0];' "$$d/lsc1_response_payload_mux.sv")" -eq 1; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/baseline.vvp" "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  vvp "$$d/baseline.vvp" >"$$d/baseline.out" 2>&1; \
	  echo "scalar-result baseline: anchor_exactly_once=PASS compile_elaboration=PASS behavior=PASS"; \
	  cp $(RTL) "$$d/"; \
	  test "$$(grep -Foc '17: payload_data = scalar_staged_write_value[7:0];' "$$d/lsc1_response_payload_mux.sv")" -eq 1; \
	  sed -i 's/17: payload_data = scalar_staged_write_value\[7:0\];/17: payload_data = scalar_staged_write_value[15:8];/' "$$d/lsc1_response_payload_mux.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/byte.vvp" "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/byte.vvp" >"$$d/byte.out" 2>&1; then echo "scalar byte-selection mutation unexpectedly survived" >&2; exit 1; fi; \
	  grep -Eq "staged write byte zero|SET result write value mismatch" "$$d/byte.out"; \
	  echo "scalar byte-selection mutant: compile_elaboration=PASS expected_behavioral_kill=PASS"; \
	  cp ../../asic_core/rtl/lsc1_packet_frontend.sv "$$d/lsc1_packet_frontend.sv"; \
	  cp ../../asic_core/rtl/lsc1_response_payload_mux.sv "$$d/lsc1_response_payload_mux.sv"; \
	  test "$$(grep -Foc 'result_length = 39;' "$$d/lsc1_packet_frontend.sv")" -eq 1; \
	  sed -i 's/result_length = 39;/result_length = 38;/' "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/length.vvp" "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/length.vvp" >"$$d/length.out" 2>&1; then echo "scalar RESULT-length mutation unexpectedly survived" >&2; exit 1; fi; \
	  grep -q "SET result payload schema mismatch" "$$d/length.out"; \
	  echo "scalar length mutant: compile_elaboration=PASS expected_behavioral_kill=PASS"; \
	  cp ../../asic_core/rtl/lsc1_packet_frontend.sv "$$d/lsc1_packet_frontend.sv"; \
	  cp ../../asic_core/rtl/lsc1_response_payload_mux.sv "$$d/lsc1_response_payload_mux.sv"; \
	  test "$$(grep -Foc '.scalar_staged_write_value(scalar_staged_write_value),' "$$d/lsc1_packet_frontend.sv")" -eq 1; \
	  sed -i 's/\.scalar_staged_write_value(scalar_staged_write_value),/.scalar_staged_write_value(write_value),/' "$$d/lsc1_packet_frontend.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/staging.vvp" "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/staging.vvp" >"$$d/staging.out" 2>&1; then echo "scalar stable-staging mutation unexpectedly survived" >&2; exit 1; fi; \
	  grep -q "scalar staged-byte/backpressure stability failed" "$$d/staging.out"; \
	  echo "scalar stable-staging mutant: compile_elaboration=PASS expected_behavioral_kill=PASS"; \
	  echo "PASS: scalar RESULT byte selection, length, CRC/stall, and stable-staging mutations detected"

differential-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  cp $(RTL) "$$d/"; \
	  sed -i.bak 's/body_index < 16'"'"'d190/body_index < 16'"'"'d94/' "$$d/lsc1_packet_rx.sv"; \
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

rx-payload-prefix:
	iverilog -g2012 -Wall -s tb_lsc1_packet_rx_payload_prefix -o tb_lsc1_packet_rx_payload_prefix.vvp \
	  ../../asic_core/rtl/lsc1_packet_rx.sv tb_lsc1_packet_rx_payload_prefix.sv
	vvp tb_lsc1_packet_rx_payload_prefix.vvp

rx-payload-prefix-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  cp ../../asic_core/rtl/lsc1_packet_rx.sv "$$d/dut.sv"; \
	  test "$$(grep -Foc 'crc <= crc_byte(crc, rx_data);' "$$d/dut.sv")" -eq 2; \
	  sed -i '/S_BODY: begin/,/end else begin/ s/crc <= crc_byte(crc, rx_data);/if (body_index < 16'"'"'d190) crc <= crc_byte(crc, rx_data);/' "$$d/dut.sv"; \
	  iverilog -g2012 -s tb_lsc1_packet_rx_payload_prefix -o "$$d/mutation.vvp" \
	    "$$d/dut.sv" tb_lsc1_packet_rx_payload_prefix.sv; \
	  if vvp "$$d/mutation.vvp" >"$$d/mutation.out" 2>&1; then \
	    echo "discarded-tail CRC mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -Eq "length 191 was not accepted byte-exactly|discarded-tail mutation did not produce BAD_CRC" "$$d/mutation.out"; \
	  echo "PASS: discarded-tail CRC-coverage mutation detected"

clean:
	rm -f tb_lsc1_response_payload_mux.vvp tb_lsc1_packet_frontend.vvp tb_lsc1_packet_tx_service_required.vvp tb_lsc1_blake3_lifecycle.vvp tb_blake3_retire_commit.vvp tb_deref_retire_trace.vvp tb_jump_retire_trace.vvp tb_scalar_retire_trace.vvp tb_lsc1_packet_rx_payload_prefix.vvp

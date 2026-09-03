PYTHON ?= python3

RTL = ../../asic_core/rtl/lsc1_packet_rx.sv \
      ../../asic_core/rtl/lsc1_packet_tx.sv \
      ../../asic_core/rtl/lsc1_response_payload_mux.sv \
      ../../asic_core/rtl/lsc1_blake3_alias_check.sv \
      ../../asic_core/rtl/lsc1_request_validator.sv \
      ../../asic_core/rtl/lsc1_cell_alias_check.sv \
      ../../asic_core/rtl/lsc1_blake3_lifecycle.sv \
      ../../asic_core/rtl/gf2n_mul_bitstream.sv \
      ../../asic_core/rtl/gf128_mul_bitstream.sv \
      ../../asic_core/rtl/leanvm_b_stream_alu.sv \
      ../../asic_core/rtl/lsc1_stream_adapter.sv \
      ../../asic_core/rtl/lsc1_field_encoder.sv \
      ../../asic_core/rtl/lsc1_packet_frontend.sv

.PHONY: sim transport response-payload-mux response-payload-mux-mutation blake3-alias-check blake3-alias-check-mutation request-validator request-validator-mutation cell-alias-check cell-alias-check-mutation serializer-structure serializer-interface-mutation lifecycle lifecycle-mutation blake3-retire-commit mutation differential-mutation duplicate-pending-mutation short-service-pending-mutation oversized-service-pending-mutation bad-version-service-mutation scalar-result-mutation short-response-mutation rx-payload-prefix rx-payload-prefix-mutation clean

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

blake3-alias-check:
	iverilog -g2012 -Wall -s tb_lsc1_blake3_alias_check -o tb_lsc1_blake3_alias_check.vvp \
	  ../../asic_core/rtl/lsc1_blake3_alias_check.sv tb_lsc1_blake3_alias_check.sv
	vvp tb_lsc1_blake3_alias_check.vvp

blake3-alias-check-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  src=../../asic_core/rtl/lsc1_blake3_alias_check.sv; \
	  for mutation in cv_companion out_companion base_swap value_blind present_blind pair_skip reduce_flip; do \
	    cp "$$src" "$$d/dut.sv"; \
	    test "$$(grep -Foc "assign address[5] = cv_offset + 1'b1;" "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc "assign address[7] = out_offset + 1'b1;" "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc 'assign address[4] = cv_offset;' "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc 'assign address[6] = out_offset;' "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc 'value[alias_i] != value[alias_j]);' "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc 'present[alias_i] != present[alias_j] ||' "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc 'if (alias_j > alias_i)' "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc 'assign alias_inconsistent = |alias_pair;' "$$d/dut.sv")" -eq 1; \
	    case $$mutation in \
	      cv_companion) sed -i "s/assign address\[5\] = cv_offset + 1'b1;/assign address[5] = cv_offset;/" "$$d/dut.sv" ;; \
	      out_companion) sed -i "s/assign address\[7\] = out_offset + 1'b1;/assign address[7] = out_offset;/" "$$d/dut.sv" ;; \
	      base_swap) sed -i 's/assign address\[4\] = cv_offset;/assign address[4] = out_offset;/; s/assign address\[6\] = out_offset;/assign address[6] = cv_offset;/' "$$d/dut.sv" ;; \
	      value_blind) sed -i "s/value\[alias_i\] != value\[alias_j\]);/1'b0);/" "$$d/dut.sv" ;; \
	      present_blind) sed -i "s/present\[alias_i\] != present\[alias_j\] ||/1'b0 ||/" "$$d/dut.sv" ;; \
	      pair_skip) sed -i 's/if (alias_j > alias_i)/if (alias_j > alias_i + 1)/' "$$d/dut.sv" ;; \
	      reduce_flip) sed -i 's/assign alias_inconsistent = |alias_pair;/assign alias_inconsistent = \&alias_pair;/' "$$d/dut.sv" ;; \
	    esac; \
	    if cmp -s "$$src" "$$d/dut.sv"; then echo "blake3-alias $$mutation mutation edited nothing" >&2; exit 1; fi; \
	    iverilog -g2012 -s tb_lsc1_blake3_alias_check -o "$$d/$$mutation.vvp" "$$d/dut.sv" tb_lsc1_blake3_alias_check.sv; \
	    if vvp "$$d/$$mutation.vvp" >"$$d/$$mutation.out" 2>&1; then echo "blake3-alias $$mutation mutation unexpectedly survived" >&2; exit 1; fi; \
	    grep -q 'FATAL:' "$$d/$$mutation.out"; \
	    echo "blake3-alias $$mutation mutant: compile_elaboration=PASS expected_behavioral_kill=PASS"; \
	  done; \
	  echo "PASS: seven BLAKE3 alias-precheck mutations behaviorally killed"

request-validator:
	iverilog -g2012 -Wall -s tb_lsc1_request_validator -o tb_lsc1_request_validator.vvp \
	  ../../asic_core/rtl/lsc1_request_validator.sv tb_lsc1_request_validator.sv
	vvp tb_lsc1_request_validator.vvp

request-validator-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  src=../../asic_core/rtl/lsc1_request_validator.sv; \
	  for mutation in jump_length blake_length cell_offset blake_stride detail_swap status_swap state_priority proposal_order; do \
	    cp "$$src" "$$d/dut.sv"; \
	    test "$$(grep -Foc "OP_JUMP:       expected_length = 16'd103;" "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc "OP_BLAKE3:     expected_length = 16'd190;" "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc 'localparam integer JUMP_CELL_1_AT = 43;' "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc 'localparam integer BLAKE_CELL_STRIDE = 17;' "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc "fault(BAD_LENGTH, payload_txn, 8'd2);" "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc "fault(BAD_PROFILE, 32'd0, 8'd0);" "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc 'end else if (cells_bad) begin' "$$d/dut.sv")" -eq 1; \
	    case $$mutation in \
	      jump_length) sed -i "s/OP_JUMP:       expected_length = 16'd103;/OP_JUMP:       expected_length = 16'd102;/" "$$d/dut.sv" ;; \
	      blake_length) sed -i "s/OP_BLAKE3:     expected_length = 16'd190;/OP_BLAKE3:     expected_length = 16'd189;/" "$$d/dut.sv" ;; \
	      cell_offset) sed -i 's/localparam integer JUMP_CELL_1_AT = 43;/localparam integer JUMP_CELL_1_AT = 44;/' "$$d/dut.sv" ;; \
	      blake_stride) sed -i 's/localparam integer BLAKE_CELL_STRIDE = 17;/localparam integer BLAKE_CELL_STRIDE = 16;/' "$$d/dut.sv" ;; \
	      detail_swap) sed -i "s/fault(BAD_LENGTH, payload_txn, 8'd2);/fault(BAD_LENGTH, payload_txn, 8'd1);/" "$$d/dut.sv" ;; \
	      status_swap) sed -i "s/fault(BAD_PROFILE, 32'd0, 8'd0);/fault(BAD_FLAGS, 32'd0, 8'd0);/" "$$d/dut.sv" ;; \
	      state_priority) sed -i 's/end else if (cells_bad) begin/end else if (cells_bad \&\& !bad_state) begin/' "$$d/dut.sv" ;; \
	      proposal_order) sed -i 's/end else if (cells_bad) begin/end else if (cells_bad \&\& !bad_proposal) begin/' "$$d/dut.sv" ;; \
	    esac; \
	    if cmp -s "$$src" "$$d/dut.sv"; then echo "request-validator $$mutation mutation edited nothing" >&2; exit 1; fi; \
	    iverilog -g2012 -s tb_lsc1_request_validator -o "$$d/$$mutation.vvp" "$$d/dut.sv" tb_lsc1_request_validator.sv; \
	    if vvp "$$d/$$mutation.vvp" >"$$d/$$mutation.out" 2>&1; then echo "request-validator $$mutation mutation unexpectedly survived" >&2; exit 1; fi; \
	    grep -q 'FATAL:' "$$d/$$mutation.out"; \
	    echo "request-validator $$mutation mutant: compile_elaboration=PASS expected_behavioral_kill=PASS"; \
	  done; \
	  echo "PASS: eight request-validation chain mutations behaviorally killed"

cell-alias-check:
	iverilog -g2012 -Wall -s tb_lsc1_cell_alias_check -o tb_lsc1_cell_alias_check.vvp \
	  ../../asic_core/rtl/lsc1_cell_alias_check.sv tb_lsc1_cell_alias_check.sv
	vvp tb_lsc1_cell_alias_check.vvp

cell-alias-check-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  src=../../asic_core/rtl/lsc1_cell_alias_check.sv; \
	  for mutation in deref_base cell_offset pair_skip present_blind value_blind opcode_widen; do \
	    cp "$$src" "$$d/dut.sv"; \
	    test "$$(grep -Foc 'wire [31:0] address_b = is_deref ? base_index + offset_b : fp + offset_b;' "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc 'localparam integer DEREF_CELL_1_AT = 47;' "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc 'assign alias_inconsistent = checked && (alias_ab || alias_ac || alias_bc);' "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc 'present_x != present_y ||' "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc 'value_x != value_y);' "$$d/dut.sv")" -eq 1; \
	    test "$$(grep -Foc 'wire is_scalar = frame_opcode == OP_JUMP ||' "$$d/dut.sv")" -eq 1; \
	    case $$mutation in \
	      deref_base) sed -i 's/wire \[31:0\] address_b = is_deref ? base_index + offset_b : fp + offset_b;/wire [31:0] address_b = fp + offset_b;/' "$$d/dut.sv" ;; \
	      cell_offset) sed -i 's/localparam integer DEREF_CELL_1_AT = 47;/localparam integer DEREF_CELL_1_AT = 43;/' "$$d/dut.sv" ;; \
	      pair_skip) sed -i 's/assign alias_inconsistent = checked \&\& (alias_ab || alias_ac || alias_bc);/assign alias_inconsistent = checked \&\& (alias_ab || alias_ac);/' "$$d/dut.sv" ;; \
	      present_blind) sed -i "s/present_x != present_y ||/1'b0 ||/" "$$d/dut.sv" ;; \
	      value_blind) sed -i "s/value_x != value_y);/1'b0);/" "$$d/dut.sv" ;; \
	      opcode_widen) sed -i "s/wire is_scalar = frame_opcode == OP_JUMP ||/wire is_scalar = frame_opcode == 8'h03 || frame_opcode == OP_JUMP ||/" "$$d/dut.sv" ;; \
	    esac; \
	    if cmp -s "$$src" "$$d/dut.sv"; then echo "cell-alias $$mutation mutation edited nothing" >&2; exit 1; fi; \
	    iverilog -g2012 -s tb_lsc1_cell_alias_check -o "$$d/$$mutation.vvp" "$$d/dut.sv" tb_lsc1_cell_alias_check.sv; \
	    if vvp "$$d/$$mutation.vvp" >"$$d/$$mutation.out" 2>&1; then echo "cell-alias $$mutation mutation unexpectedly survived" >&2; exit 1; fi; \
	    grep -q 'FATAL:' "$$d/$$mutation.out"; \
	    echo "cell-alias $$mutation mutant: compile_elaboration=PASS expected_behavioral_kill=PASS"; \
	  done; \
	  echo "PASS: six three-cell alias-precheck mutations behaviorally killed"

sim:
	$(MAKE) serializer-structure
	$(MAKE) blake3-alias-check
	$(MAKE) request-validator
	$(MAKE) cell-alias-check
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
	  sed -i.bak "s/OP_SET:        expected_length = 16'd51;/OP_SET:        expected_length = frame_length;/" \
	    "$$d/lsc1_request_validator.sv"; \
	  if cmp -s ../../asic_core/rtl/lsc1_request_validator.sv "$$d/lsc1_request_validator.sv"; then \
	    echo "BAD_LENGTH-order mutation edited nothing" >&2; exit 1; \
	  fi; \
	  iverilog -g2012 -s tb_lsc1_packet_frontend -o "$$d/length.vvp" \
	    "$$d"/*.sv tb_lsc1_packet_frontend.sv; \
	  if vvp "$$d/length.vvp" >"$$d/length.out" 2>&1; then \
	    echo "BAD_LENGTH-order mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -q "status got=87 expected=83" "$$d/length.out"; \
	  echo "PASS: BUSY, SET value, RETIRE ID, ABORT, and length-order mutations were detected"
	$(MAKE) blake3-alias-check-mutation
	$(MAKE) request-validator-mutation
	$(MAKE) duplicate-pending-mutation
	$(MAKE) short-service-pending-mutation
	$(MAKE) oversized-service-pending-mutation
	$(MAKE) bad-version-service-mutation
	$(MAKE) cell-alias-check-mutation
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

duplicate-pending-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  cp $(RTL) "$$d/"; \
	  src="$$d/lsc1_request_validator.sv"; \
	  test "$$(grep -Foc 'wire bad_state = result_pending || blake_result_pending || blake_service_pending;' "$$src")" -eq 1; \
	  sed -i 's/wire bad_state = result_pending || blake_result_pending || blake_service_pending;/wire bad_state = result_pending || blake_result_pending;/' "$$src"; \
	  if PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=../.. LSC1_RTL_DIR="$$d" $(PYTHON) -m unittest \
	      sim.test_conformance_v3_rtl_differential.ConformanceV3RtlDifferentialTests.test_duplicate_blake3_request_preserves_original_pending_then_retires \
	      >"$$d/mutation.out" 2>&1; then \
	    echo "duplicate-pending admission mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -Eq 'FAILED|AssertionError' "$$d/mutation.out"; \
	  echo "PASS: duplicate-pending admission mutant compile/elaboration and behavioral kill"

short-service-pending-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  cp $(RTL) "$$d/"; \
	  src="$$d/lsc1_packet_frontend.sv"; \
	  test "$$(grep -Foc 'if (frame_length != 42) begin' "$$src")" -eq 1; \
	  sed -i 's/if (frame_length != 42) begin/if (frame_length != 41) begin/' "$$src"; \
	  if PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=../.. LSC1_RTL_DIR="$$d" $(PYTHON) -m unittest \
	      sim.test_conformance_v3_rtl_differential.ConformanceV3RtlDifferentialTests.test_short_service_response_preserves_pending_then_retry_retires \
	      >"$$d/mutation.out" 2>&1; then \
	    echo "short-service pending-length mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -Eq 'FAILED|AssertionError' "$$d/mutation.out"; \
	  echo "PASS: short-service pending-length mutant compile/elaboration and behavioral kill"

oversized-service-pending-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  cp $(RTL) "$$d/"; \
	  src="$$d/lsc1_packet_frontend.sv"; \
	  test "$$(grep -Foc 'if (frame_length != 42) begin' "$$src")" -eq 1; \
	  sed -i 's/if (frame_length != 42) begin/if (frame_length != 43) begin/' "$$src"; \
	  if PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=../.. LSC1_RTL_DIR="$$d" $(PYTHON) -m unittest \
	      sim.test_conformance_v3_rtl_differential.ConformanceV3RtlDifferentialTests.test_oversized_service_response_preserves_pending_then_retry_retires \
	      >"$$d/mutation.out" 2>&1; then \
	    echo "oversized-service pending-length mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -Eq 'FAILED|AssertionError' "$$d/mutation.out"; \
	  echo "PASS: oversized-service pending-length mutant compile/elaboration and behavioral kill"

bad-version-service-mutation:
	@set -e; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  cp $(RTL) "$$d/"; \
	  src="$$d/lsc1_packet_rx.sv"; \
	  test "$$(grep -Foc 'else if (version != VERSION)' "$$src")" -eq 1; \
	  sed -i 's/else if (version != VERSION)/else if (version == 8'"'"'hff)/' "$$src"; \
	  if PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=../.. LSC1_RTL_DIR="$$d" $(PYTHON) -m unittest \
	      sim.test_conformance_v3_rtl_differential.ConformanceV3RtlDifferentialTests.test_service_response_bad_version_preserves_pending_then_retry_retires \
	      >"$$d/mutation.out" 2>&1; then \
	    echo "BAD_VERSION receiver mutation unexpectedly survived" >&2; exit 1; \
	  fi; \
	  grep -Eq 'FAILED|AssertionError' "$$d/mutation.out"; \
	  echo "PASS: BAD_VERSION receiver mutant compile/elaboration and behavioral kill"

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
	rm -f tb_lsc1_response_payload_mux.vvp tb_lsc1_blake3_alias_check.vvp tb_lsc1_request_validator.vvp tb_lsc1_cell_alias_check.vvp tb_lsc1_packet_frontend.vvp tb_lsc1_packet_tx_service_required.vvp tb_lsc1_blake3_lifecycle.vvp tb_blake3_retire_commit.vvp tb_deref_retire_trace.vvp tb_jump_retire_trace.vvp tb_scalar_retire_trace.vvp tb_lsc1_packet_rx_payload_prefix.vvp

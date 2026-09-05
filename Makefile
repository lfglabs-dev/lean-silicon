PYTHON ?= python3

.PHONY: check python workflow-check fabrication-bundle conformance-check conformance-differential scalar-differential m2-differential host-export host-comparison workload-validation design-space exact-xor interface-check consistency checksum-check smoke placeholders fpga-boundary fpga-harness fpga-detect fpga-preflight lsc1u-host-test silicon-bringup-test silicon-bringup-dry-run mincore-state-count sim lean lsc1-authored-rtl-contract lsc1-host-authored-rtl-boundary lsc1-retire-mismatch-host-boundary lsc1-retire-txn-mismatch-host-boundary lsc1-blake3-status-host-boundary lsc1-blake3-status-host-boundary-mutation lsc1-scalar-status-host-boundary lsc1-scalar-status-host-boundary-mutation lsc1-scalar-post-retire-status lsc1-scalar-post-retire-status-mutation formal formal-mutations formal-deref-coverage-mutation formal-jump-coverage-mutation full-profile-assurance full-lsc1-netlist-assurance release-netlist-equivalence clean package checksums

HOST_SOURCE ?= host/fixtures/assert_set_xor_mul.zkdsl
HOST_ARTIFACT ?= host/fixtures/assert_set_xor_mul.program.json

python:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s sim -v

workflow-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) test/test_select_exact_gds_run.py -v
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) test/test_viewer_workflow.py -v
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) test/test_lean_mutation_workflow.py -v
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) test/test_lsc1_blake3_status_workflow.py -v
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) test/test_lsc1_scalar_status_workflow.py -v
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) test/test_oss_cad_suite_workflow.py -v
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. $(PYTHON) test/test_lsc1_fpga_packet_evidence.py -v

fabrication-bundle:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify_fabrication_bundle.py
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) test/test_fabrication_bundle.py -v

conformance-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/conformance_differential.py --validate-only

conformance-differential:
	@test -n "$(LEANVM_B_UPSTREAM)" || (echo "set LEANVM_B_UPSTREAM to leanEthereum/leanVM-b@c308034..." >&2; exit 2)
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/conformance_differential.py --upstream "$(LEANVM_B_UPSTREAM)"

scalar-differential:
	@test -n "$(LEANVM_B_UPSTREAM)" || (echo "set LEANVM_B_UPSTREAM to leanEthereum/leanVM-b@c308034..." >&2; exit 2)
	$(PYTHON) tools/frozen_upstream_differential.py --upstream "$(LEANVM_B_UPSTREAM)"

m2-differential:
	@test -n "$(LEANVM_B_UPSTREAM)" || (echo "set LEANVM_B_UPSTREAM to leanEthereum/leanVM-b@c308034..." >&2; exit 2)
	$(PYTHON) tools/m2_rtl_differential.py --upstream "$(LEANVM_B_UPSTREAM)"

# Regenerates the checked-in program artifact from the frozen upstream compiler.
host-export:
	@test -n "$(LEANVM_B_UPSTREAM)" || (echo "set LEANVM_B_UPSTREAM to leanEthereum/leanVM-b@c308034..." >&2; exit 2)
	$(PYTHON) tools/lean_compiler_export.py --upstream "$(LEANVM_B_UPSTREAM)" \
	  --source $(HOST_SOURCE) --out $(HOST_ARTIFACT) \
	  --rust-toolchain leanvm-validation-1.88.0

# Without LEANVM_B_UPSTREAM this compares against the recorded upstream run.
host-comparison:
	$(PYTHON) -I tools/host_upstream_comparison.py --artifact $(HOST_ARTIFACT) \
	  $(if $(LEANVM_B_UPSTREAM),--upstream "$(LEANVM_B_UPSTREAM)" \
	  --rust-toolchain leanvm-validation-1.88.0,)

# Non-release, non-SKY26c realistic workload lane. Both paths are caller-owned.
workload-validation:
	@test -n "$(WORKLOAD_CACHE)" || (echo "set WORKLOAD_CACHE to a private directory outside the checkout" >&2; exit 2)
	@test -n "$(LEANVM_B_UPSTREAM)" || (echo "set LEANVM_B_UPSTREAM to leanEthereum/leanVM-b@c308034..." >&2; exit 2)
	$(PYTHON) -I tools/workload_validation.py --cache-dir "$(WORKLOAD_CACHE)" --upstream "$(LEANVM_B_UPSTREAM)"

design-space:
	$(PYTHON) tools/design_space.py

exact-xor:
	$(PYTHON) tools/exact_linear_xor.py

interface-check:
	$(PYTHON) tools/interface_consistency.py

consistency:
	$(PYTHON) tools/repo_consistency.py

mincore-state-count:
	$(PYTHON) tools/rtl_state_count.py

smoke:
	$(PYTHON) tools/sv_smoke_check.py asic_core/rtl/*.sv src/leanvm_b_m2_scalar_controller.sv formal/*.sv test/tb_stream_alu.sv test/tb_m2_scalar_controller.sv fpga_harness/rtl/*.sv

placeholders:
	@! grep -RInE '\\b(sorry|admit|axiom)\\b' lean/LeanVMBMinCore*.lean lean/LeanVMBMinCore || \
	  (echo "Lean proof placeholder found" >&2; exit 1)

fpga-boundary:
	$(PYTHON) fpga_harness/boundary_check.py

fpga-harness:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s fpga_harness -v

lsc1u-host-test:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest fpga_harness.test_lsc1u_protocol -v

silicon-bringup-test:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest silicon_bringup.test_bringup -v

silicon-bringup-dry-run:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m silicon_bringup.dry_run

# Reporting only: absent tools or absent board must not fail a build.
fpga-detect:
	$(PYTHON) fpga_harness/board_detect.py

fpga-preflight:
	$(PYTHON) fpga_harness/hardware_preflight.py

check: python workflow-check fabrication-bundle conformance-check host-comparison design-space exact-xor interface-check consistency silicon-bringup-test checksum-check mincore-state-count smoke placeholders fpga-boundary fpga-harness

sim:
	$(MAKE) -C test sim

lean:
	cd lean && lake build
	cd lean && lake build LeanVMBMinCore
	cd lean && python3 check_full_profile_mutations.py
	cd lean && python3 check_accepted_deref_binding_mutations.py
	cd lean && python3 check_accepted_jump_binding_mutations.py
	cd lean && python3 check_accepted_scalar_binding_mutations.py
	cd lean && python3 check_accepted_sequence_mutations.py

lsc1-authored-rtl-contract:
	$(PYTHON) tools/lsc1_authored_rtl_contract.py --verify

lsc1-host-authored-rtl-boundary:
	$(PYTHON) tools/lsc1_host_authored_rtl_boundary.py --verify

lsc1-retire-mismatch-host-boundary:
	$(PYTHON) tools/lsc1_retire_mismatch_host_boundary.py

lsc1-retire-txn-mismatch-host-boundary:
	$(PYTHON) tools/lsc1_retire_mismatch_host_boundary.py --txn-id

lsc1-blake3-status-host-boundary:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/lsc1_blake3_status_host_boundary.py

lsc1-blake3-status-host-boundary-mutation:
	@set -eu; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  src=asic_core/rtl/lsc1_packet_frontend.sv; mutant="$$d/lsc1_packet_frontend.sv"; \
	  cp "$$src" "$$mutant"; \
	  test "$$(grep -Foc '(blake_result_pending || blake_service_pending) ?' "$$mutant")" -eq 1; \
	  sed -i 's/(blake_result_pending || blake_service_pending) ?/(blake_result_pending) ?/' "$$mutant"; \
	  if PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/lsc1_blake3_status_host_boundary.py --frontend "$$mutant" >"$$d/output" 2>&1; then \
	    echo "STATUS BLAKE3 txn-id selection mutation unexpectedly survived" >&2; cat "$$d/output"; exit 1; \
	  fi; \
	  grep -Fq 'authored RTL response bytes differ from executable model' "$$d/output"; \
	  echo 'LSC1_BLAKE3_STATUS_MUTATION_PASS compile_elaboration=PASS behavioral_kill=PASS'

lsc1-scalar-status-host-boundary:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/lsc1_scalar_status_host_boundary.py

lsc1-scalar-status-host-boundary-mutation:
	@set -eu; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  src=asic_core/rtl/lsc1_packet_frontend.sv; mutant="$$d/lsc1_packet_frontend.sv"; \
	  cp "$$src" "$$mutant"; \
	  arm='blake_staged_txn_id : (result_pending ? staged_txn_id : 0)'; \
	  test "$$(grep -Foc "$$arm" "$$mutant")" -eq 1; \
	  sed -i 's/blake_staged_txn_id : (result_pending ? staged_txn_id : 0)/blake_staged_txn_id : (result_pending ? 0 : 0)/' "$$mutant"; \
	  if PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/lsc1_scalar_status_host_boundary.py --frontend "$$mutant" >"$$d/output" 2>&1; then \
	    echo "STATUS scalar txn-id selection mutation unexpectedly survived" >&2; cat "$$d/output"; exit 1; \
	  fi; \
	  grep -Fq 'authored RTL response bytes differ from executable model' "$$d/output"; \
	  echo 'LSC1_SCALAR_STATUS_MUTATION_PASS txn_id=0 compile_elaboration=PASS behavioral_kill=PASS'

lsc1-scalar-post-retire-status:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/lsc1_scalar_post_retire_status.py

lsc1-scalar-post-retire-status-mutation:
	@set -eu; d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	  src=asic_core/rtl/lsc1_response_payload_mux.sv; mutant="$$d/lsc1_response_payload_mux.sv"; \
	  cp "$$src" "$$mutant"; \
	  arm='19: payload_data = state_valid;'; \
	  test "$$(grep -Foc "$$arm" "$$mutant")" -eq 1; \
	  sed -i 's/19: payload_data = state_valid;/19: payload_data = 0;/' "$$mutant"; \
	  if PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/lsc1_scalar_post_retire_status.py --payload-mux "$$mutant" >"$$d/output" 2>&1; then \
	    echo "STATUS state_valid serialization mutation unexpectedly survived" >&2; cat "$$d/output"; exit 1; \
	  fi; \
	  grep -Fq 'authored RTL response bytes differ from executable model' "$$d/output"; \
	  echo 'LSC1_SCALAR_POST_RETIRE_STATUS_MUTATION_PASS state_valid=0 compile_elaboration=PASS behavioral_kill=PASS'

formal:
	$(PYTHON) formal/run_deref_bridge_tasks.py
	cd formal && sby -f gf8_mul.sby
	cd formal && sby -f lsc1u_protocol.sby
	cd formal && sby -f lsc1u_reachability.sby
	cd formal && sby -f lsc1u_xor_refinement.sby
	cd formal && sby -f gf128_mul_stream_refinement.sby
	cd formal && sby -f lsc1u_compositional_refinement.sby

formal-mutations:
	$(PYTHON) formal/check_mutations.py
	$(PYTHON) formal/check_deref_mutations.py

formal-deref-coverage-mutation:
	$(PYTHON) -m unittest formal/test_deref_task_serialization.py -v
	$(PYTHON) -m unittest formal/test_deref_retire_formal_mutations.py -v
	$(PYTHON) -m unittest formal/test_blake3_pending_invariant.py -v
	$(PYTHON) formal/check_blake3_pending_invariant.py
	$(PYTHON) formal/check_deref_coverage_mutation.py
	$(PYTHON) formal/check_deref_retire_formal_mutations.py

formal-jump-coverage-mutation:
	$(PYTHON) formal/check_jump_coverage_mutation.py
	$(PYTHON) formal/check_jump_retire_formal_mutations.py

formal-scalar-mutations:
	$(PYTHON) formal/check_scalar_retire_formal_mutations.py

# Non-release, non-SKY26c lane. The cache must remain private and outside the checkout.
full-profile-assurance:
	@test -n "$(LSC1_FULL_CACHE)" || (echo "set LSC1_FULL_CACHE to a private directory outside the checkout" >&2; exit 2)
	$(PYTHON) tools/full_profile_assurance.py --cache-dir "$(LSC1_FULL_CACHE)" --verify

# Canonical full-profile generic synthesis and formal correspondence lane.
full-lsc1-netlist-assurance:
	@test -n "$(LSC1_FULL_NETLIST_CACHE)" || (echo "set LSC1_FULL_NETLIST_CACHE to a private directory outside the checkout" >&2; exit 2)
	$(PYTHON) tools/full_lsc1_netlist.py --cache-dir "$(LSC1_FULL_NETLIST_CACHE)"

release-netlist-equivalence:
	@test -n "$(LSC1_EQ_CACHE)" || (echo "set LSC1_EQ_CACHE to a private directory outside the checkout" >&2; exit 2)
	$(PYTHON) tools/verify_lsc1u_release_equivalence.py --cache-dir "$(LSC1_EQ_CACHE)"

clean:
	$(MAKE) -C test clean
	rm -rf lean/.lake sim/__pycache__ fpga_harness/__pycache__

package: check
	tar --exclude='__pycache__' --exclude='.lake' -czf ../lean-silicon-lsc1.tar.gz .

checksums:
	$(PYTHON) tools/generate_checksums.py > SHA256SUMS

checksum-check:
	$(PYTHON) tools/generate_checksums.py --check

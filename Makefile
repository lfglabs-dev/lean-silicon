PYTHON ?= python3

.PHONY: check python scalar-differential m2-differential design-space exact-xor interface-check consistency checksum-check smoke placeholders fpga-boundary fpga-harness fpga-detect sim lean formal clean package checksums

python:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s sim -v

scalar-differential:
	@test -n "$(LEANVM_B_UPSTREAM)" || (echo "set LEANVM_B_UPSTREAM to leanEthereum/leanVM-b@c308034..." >&2; exit 2)
	$(PYTHON) tools/frozen_upstream_differential.py --upstream "$(LEANVM_B_UPSTREAM)"

m2-differential:
	@test -n "$(LEANVM_B_UPSTREAM)" || (echo "set LEANVM_B_UPSTREAM to leanEthereum/leanVM-b@c308034..." >&2; exit 2)
	$(PYTHON) tools/m2_rtl_differential.py --upstream "$(LEANVM_B_UPSTREAM)"

design-space:
	$(PYTHON) tools/design_space.py

exact-xor:
	$(PYTHON) tools/exact_linear_xor.py

interface-check:
	$(PYTHON) tools/interface_consistency.py

consistency:
	$(PYTHON) tools/repo_consistency.py

gate-count:
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

# Reporting only: absent tools or absent board must not fail a build.
fpga-detect:
	$(PYTHON) fpga_harness/board_detect.py

check: python design-space exact-xor interface-check consistency checksum-check gate-count smoke placeholders fpga-boundary fpga-harness

sim:
	$(MAKE) -C test sim

lean:
	cd lean && lake build
	cd lean && lake build LeanVMBMinCore

formal:
	cd formal && sby -f gf8_mul.sby

clean:
	$(MAKE) -C test clean
	rm -rf lean/.lake sim/__pycache__ fpga_harness/__pycache__

package: check
	tar --exclude='__pycache__' --exclude='.lake' -czf ../lean-silicon-lsc1.tar.gz .

checksums:
	$(PYTHON) tools/generate_checksums.py > SHA256SUMS

checksum-check:
	$(PYTHON) tools/generate_checksums.py --check

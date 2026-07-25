PYTHON ?= python3

.PHONY: check python scalar-differential m2-differential design-space exact-xor interface-check smoke placeholders sim lean formal clean package

python:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s sim -v

scalar-differential:
	@test -n "$(LEANVM_B_UPSTREAM)" || (echo "set LEANVM_B_UPSTREAM to leanEthereum/leanVM-b@c308034..." >&2; exit 2)
	$(PYTHON) tools/frozen_upstream_differential.py --upstream "$(LEANVM_B_UPSTREAM)" --record results/oracle-differential-20260725/differential.log

m2-differential:
	$(PYTHON) tools/m2_rtl_differential.py

design-space:
	$(PYTHON) tools/design_space.py

exact-xor:
	$(PYTHON) tools/exact_linear_xor.py

interface-check:
	$(PYTHON) tools/interface_consistency.py

gate-count:
	$(PYTHON) tools/rtl_state_count.py

smoke:
	$(PYTHON) tools/sv_smoke_check.py src/*.sv formal/*.sv test/tb_stream_alu.sv test/tb_m2_scalar_controller.sv

placeholders:
	@! grep -RInE '\\b(sorry|admit|axiom)\\b' lean/LeanVMBMinCore*.lean lean/LeanVMBMinCore || \
	  (echo "Lean proof placeholder found" >&2; exit 1)

check: python design-space exact-xor interface-check gate-count smoke placeholders

sim:
	$(MAKE) -C test sim

lean:
	cd lean && lake build
	cd lean && lake build LeanVMBMinCore

formal:
	cd formal && sby -f gf8_mul.sby

clean:
	$(MAKE) -C test clean
	rm -rf lean/.lake sim/__pycache__

package: check
	tar --exclude='__pycache__' --exclude='.lake' -czf ../leanvm-b-mincore.tar.gz .

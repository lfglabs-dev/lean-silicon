PYTHON ?= python3

.PHONY: check python design-space exact-xor interface-check smoke placeholders sim lean formal clean package

python:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s sim -v

design-space:
	$(PYTHON) tools/design_space.py

exact-xor:
	$(PYTHON) tools/exact_linear_xor.py

interface-check:
	$(PYTHON) tools/interface_consistency.py

gate-count:
	$(PYTHON) tools/rtl_state_count.py

smoke:
	$(PYTHON) tools/sv_smoke_check.py src/*.sv formal/*.sv test/tb_stream_alu.sv

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

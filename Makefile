.PHONY: check python design-space exact-xor interface-check smoke placeholders sim lean formal clean package

python:
	PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s sim -v

design-space:
	python tools/design_space.py

exact-xor:
	python tools/exact_linear_xor.py

interface-check:
	python tools/interface_consistency.py

gate-count:
	python tools/rtl_state_count.py

smoke:
	python tools/sv_smoke_check.py src/*.sv formal/*.sv test/tb_stream_alu.sv

placeholders:
	@! grep -RInE '\\b(sorry|admit|axiom)\\b' lean/LeanVMBMinCore*.lean lean/LeanVMBMinCore || \
	  (echo "Lean proof placeholder found" >&2; exit 1)

check: python design-space exact-xor interface-check gate-count smoke placeholders

sim:
	$(MAKE) -C test sim

lean:
	cd lean && lake build

formal:
	cd formal && sby -f gf8_mul.sby

clean:
	$(MAKE) -C test clean
	rm -rf lean/.lake sim/__pycache__

package: check
	tar --exclude='__pycache__' --exclude='.lake' -czf ../leanvm-b-mincore.tar.gz .

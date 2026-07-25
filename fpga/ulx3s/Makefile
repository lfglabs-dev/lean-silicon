# Local FPGA make targets for the sprint worktree
# These are intentionally NOT wired into the repo root Makefile.
# Run from this directory after sourcing an OSS CAD Suite env.

SHELL := /bin/sh
PYTHON ?= python3

.PHONY: smoke uart sim clean

smoke:
	./build_smoke.sh

uart:
	@echo "UART bridge build requires full core integration; see build_uart.sh (TBD in sprint)"

sim:
	$(MAKE) -C ../../../test sim || true
	$(PYTHON) -m unittest discover -s ../../../fpga_harness -v

clean:
	rm -f *.json *.config *.bit *.svf *.log

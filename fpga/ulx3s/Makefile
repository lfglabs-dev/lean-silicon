# Local FPGA make targets for the sprint worktree
# These are intentionally NOT wired into the repo root Makefile.
# Run from this directory after sourcing an OSS CAD Suite env.

SHELL := /bin/sh
PYTHON ?= python3
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)

.PHONY: smoke uart sim clean

smoke:
	./build_smoke.sh

uart:
	./build_uart.sh

sim:
	$(MAKE) -C $(ROOT)/test sim
	cd $(ROOT) && $(PYTHON) -m unittest discover -s fpga_harness -v

clean:
	rm -f *.json *.config *.bit *.svf *.log

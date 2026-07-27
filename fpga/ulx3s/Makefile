# Local FPGA make targets for the sprint worktree
# These are intentionally NOT wired into the repo root Makefile.
# Run from this directory after sourcing an OSS CAD Suite env.

SHELL := /bin/sh
PYTHON ?= python3
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)

.PHONY: smoke uart packet-uart sim clean

smoke:
	./build_smoke.sh

uart:
	./build_uart.sh

packet-uart:
	./build_packet_uart.sh

sim:
	$(MAKE) -C $(ROOT)/test sim
	cd $(ROOT) && $(PYTHON) -m unittest discover -s fpga_harness -v

clean:
	rm -f smoke_top.json smoke_top.config smoke_top.bit smoke_top.svf
	rm -f ulx3s_top.json ulx3s_top.config ulx3s_top.bit ulx3s_top.svf
	rm -f ulx3s_packet_top.json ulx3s_packet_top.config ulx3s_packet_top.bit ulx3s_packet_top.svf
	rm -f ecppack.log ecppack_uart.log

#!/bin/sh
# Reproducible, bounded architectural-state milestones.  This is intentionally
# not a timeout extension for release equivalence.
set -eu
out=${1:-results/arch-state-20260728}
mkdir -p "$out"
{
  git rev-parse HEAD
  git rev-parse HEAD^{tree}
  yosys -V
  iverilog -V 2>&1 | head -1
  sha256sum asic_core/rtl/lsc1_packet_rx.sv asic_core/rtl/lsc1_packet_tx.sv \
    asic_core/rtl/lsc1_stream_adapter.sv asic_core/rtl/lsc1_field_encoder.sv \
    asic_core/rtl/lsc1_packet_frontend.sv formal/lsc1_packet_frontend_arch_state_map.json formal/ARCH_STATE.md \
    formal/lsc1_packet_frontend_arch_reset_idle.sv formal/lsc1_packet_frontend_arch_reset_idle.ys
} > "$out/versions-and-inputs.log"
python3 tools/check_arch_state_interface.py > "$out/interface-coverage.log" 2>&1
yosys -s formal/lsc1_packet_frontend_arch_reset_idle.ys 2>&1 | sed 's/[[:space:]]*$//' > "$out/reset-idle.log"
make -C test/packet_frontend sim > "$out/rtl.log" 2>&1
python3 -m unittest sim.test_packet_frontend_rtl_differential -v > "$out/differential.log" 2>&1
make -C test/packet_frontend mutation > "$out/mutation.log" 2>&1
sha256sum "$out"/*.log > "$out/SHA256SUMS"

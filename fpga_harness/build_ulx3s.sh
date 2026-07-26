#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir="$repo_dir/build/ulx3s"
mkdir -p "$build_dir"
rm -f "$build_dir/lsc1.json" "$build_dir/lsc1.config" "$build_dir/lsc1.bit"

if ! yosys -p "read_verilog -sv \
  $repo_dir/asic_core/rtl/gf2n_mul_bitstream.sv \
  $repo_dir/asic_core/rtl/gf128_mul_bitstream.sv \
  $repo_dir/asic_core/rtl/leanvm_b_stream_alu.sv \
  $repo_dir/asic_core/rtl/lean_silicon_lsc1.sv \
  $repo_dir/fpga_harness/rtl/uart_rx.sv \
  $repo_dir/fpga_harness/rtl/uart_tx.sv \
  $repo_dir/fpga_harness/rtl/ulx3s_lsc1_top.sv; \
  synth_ecp5 -top ulx3s_lsc1_top -json $build_dir/lsc1.json" \
  >"$build_dir/yosys.log" 2>&1; then
  cat "$build_dir/yosys.log"
  exit 1
fi
cat "$build_dir/yosys.log"

if ! nextpnr-ecp5 --85k --package CABGA381 --speed 6 \
  --json "$build_dir/lsc1.json" --lpf "$repo_dir/fpga_harness/ulx3s_v308.lpf" \
  --textcfg "$build_dir/lsc1.config" --freq 25 \
  >"$build_dir/nextpnr.log" 2>&1; then
  cat "$build_dir/nextpnr.log"
  exit 1
fi
cat "$build_dir/nextpnr.log"

ecppack --compress "$build_dir/lsc1.config" "$build_dir/lsc1.bit"
shasum -a 256 "$build_dir/lsc1.bit" > "$build_dir/lsc1.bit.sha256"

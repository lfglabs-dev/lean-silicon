#!/usr/bin/env bash
set -u -o pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
out="$root/results/m0-merge-20260724T210000Z"
cd "$root"

run() {
  local name=$1
  shift
  {
    printf '+ '
    printf '%q ' "$@"
    printf '\n'
    "$@"
  } >"$out/$name.log" 2>&1
  local status=$?
  printf '%s %s\n' "$name" "$status" >>"$out/status.tsv"
  return "$status"
}

{
  date -u +'%Y-%m-%dT%H:%M:%SZ'
  git rev-parse HEAD
  git status --short
  python3 --version
  make --version | head -n 1
  iverilog -V | head -n 2
  yosys -V
  sby --version
  boolector --version
  lake --version
} >"$out/versions.log" 2>&1

status=0
: >"$out/status.tsv"
run make-check make check || status=1
run make-sim make sim || status=1
run lean-build bash -lc 'cd lean && lake build' || status=1
run formal-sby timeout --foreground 45s bash -lc 'cd formal && sby -f gf8_mul.sby' || status=1
run yosys-rtl yosys -ql "$out/yosys-rtl.internal.log" -p 'read_verilog -sv src/gf2n_mul_bitstream.sv src/gf128_mul_bitstream.sv src/leanvm_b_stream_alu.sv src/tt_um_leanvm_b_mincore.sv; hierarchy -check -top tt_um_leanvm_b_mincore; proc; check; synth -top tt_um_leanvm_b_mincore; stat' || status=1
run yosys-formal yosys -ql "$out/yosys-formal.internal.log" -p 'read_verilog -formal -sv src/gf2n_mul_bitstream.sv formal/gf8_mul_formal.sv; prep -top gf8_mul_formal; check; synth -top gf8_mul_formal; stat' || status=1
exit "$status"

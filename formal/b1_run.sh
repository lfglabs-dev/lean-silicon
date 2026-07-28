#!/usr/bin/env bash
# Recreate B1's local formal/equivalence receipts from a checkout of this branch.
set -euo pipefail
script_dir=$(cd "$(dirname "$0")" && pwd)
repo=$(git -C "$script_dir/.." rev-parse --show-toplevel)
out="$repo/results/b1-rtl-formal-equivalence-20260728"
cleanup_smt() {
  rm -f "$repo/formal/b1_packet_tx_equiv.smt2" "$repo/formal/b1_packet_rx_fault.smt2"
}
trap cleanup_smt EXIT
mkdir -p "$out"
{
  git --version
  yosys -V
  yosys-smtbmc -h | head -1
  cvc5 --version | head -1
  iverilog -V | head -1
} > "$out/toolchain.txt" 2>&1
git -C "$repo" rev-parse HEAD > "$out/tested-commit.txt"
git -C "$repo" rev-parse HEAD^{tree} > "$out/tested-tree.txt"
(
  cd "$repo/formal"
  yosys -ql "$out/tx-elaboration.log" -s b1_packet_tx_equiv.ys
  yosys-smtbmc -s cvc5 --presat --noprogress -t 16 b1_packet_tx_equiv.smt2
) > "$out/tx-formal.log" 2>&1
(
  cd "$repo/formal"
  yosys -ql "$out/rx-fault-elaboration.log" -s b1_packet_rx_fault.ys
  yosys-smtbmc -s cvc5 --presat --noprogress -t 6 b1_packet_rx_fault.smt2
) > "$out/rx-fault-formal.log" 2>&1
(
  cd "$repo/formal"
  iverilog -g2012 -Wall -s b1_packet_equiv_tb -o /tmp/b1-packet-tb.vvp \
    ../asic_core/rtl/lsc1_packet_tx.sv b1_packet_equiv_tb.sv
  vvp /tmp/b1-packet-tb.vvp
) > "$out/tx-stall-simulation.log" 2>&1
mut=$(mktemp -d)
trap 'rm -rf "$mut"; cleanup_smt' EXIT
cp "$repo/formal/b1_packet_tx_equiv_formal.sv" "$mut/mut.sv"
sed -i "s/8'h3f/8'h3e/" "$mut/mut.sv"
yosys -q -p "read_verilog -formal -sv $repo/asic_core/rtl/lsc1_packet_tx.sv $mut/mut.sv; prep -top b1_packet_tx_equiv_formal; write_smt2 -wires $mut/mut.smt2"
if yosys-smtbmc -s cvc5 --presat --noprogress -t 16 "$mut/mut.smt2" > "$out/tx-mutation.log" 2>&1; then
  echo 'ERROR: mutation unexpectedly passed' >&2
  exit 1
fi
grep -q 'Status: FAILED' "$out/tx-mutation.log"
(cd "$out" && sha256sum -- toolchain.txt tested-commit.txt tested-tree.txt \
  tx-elaboration.log tx-formal.log rx-fault-elaboration.log rx-fault-formal.log \
  tx-stall-simulation.log tx-mutation.log > SHA256SUMS)

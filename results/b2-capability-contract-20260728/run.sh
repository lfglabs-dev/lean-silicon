#!/usr/bin/env bash
# Reproduce the bounded Phase-B capability-contract evidence from repo root.
set -u -o pipefail

out=results/b2-capability-contract-20260728
mkdir -p "$out"
printf '%s\n' "baseline_commit=$(git rev-parse fda85f5efc6f5b460d72204b4d9c0d882960ec29)" > "$out/metadata.txt"
printf '%s\n' "baseline_tree=$(git rev-parse fda85f5efc6f5b460d72204b4d9c0d882960ec29^{tree})" >> "$out/metadata.txt"
printf '%s\n' "head=$(git rev-parse HEAD)" >> "$out/metadata.txt"
printf '%s\n' "head_tree=$(git rev-parse HEAD^{tree})" >> "$out/metadata.txt"

run() {
    name=$1
    shift
    printf '%q ' "$@" > "$out/$name.command"
    printf '\n' >> "$out/$name.command"
    start=$(date +%s%N)
    "$@" > "$out/$name.log" 2>&1
    status=$?
    end=$(date +%s%N)
    printf 'exit_code=%s\nduration_ms=%s\n' "$status" "$(((end - start) / 1000000))" > "$out/$name.status"
    return "$status"
}

rtl=(asic_core/rtl/lsc1_packet_rx.sv asic_core/rtl/lsc1_packet_tx.sv
     asic_core/rtl/gf2n_mul_bitstream.sv asic_core/rtl/gf128_mul_bitstream.sv
     asic_core/rtl/leanvm_b_stream_alu.sv asic_core/rtl/lsc1_stream_adapter.sv
     asic_core/rtl/lsc1_field_encoder.sv asic_core/rtl/lsc1_packet_frontend.sv)

run model timeout 180s python3 -m unittest sim.test_packet_frontend_rtl_differential -v || exit $?
run rtl timeout 180s make -C test/packet_frontend sim || exit $?
run mutation timeout 180s make -C test/packet_frontend mutation || exit $?
run netlist timeout 180s yosys -p "read_verilog -sv ${rtl[*]}; hierarchy -check -top lsc1_packet_frontend; proc; memory; flatten; opt; check; write_verilog -noattr $out/lsc1_packet_frontend.netlist.v; stat" || exit $?
run equivalence timeout 180s yosys -p "read_verilog -formal -sv ${rtl[*]}; hierarchy -top lsc1_packet_frontend; proc; memory; flatten; opt; rename lsc1_packet_frontend gold; read_verilog -formal $out/lsc1_packet_frontend.netlist.v; rename lsc1_packet_frontend gate; equiv_make gold gate equiv; hierarchy -top equiv; prep -top equiv; equiv_simple; equiv_status -assert" || exit $?
sha256sum "$out"/*.command "$out"/*.log "$out"/*.status "$out"/metadata.txt "$out"/lsc1_packet_frontend.netlist.v > "$out/SHA256SUMS"

#!/usr/bin/env bash
# Reproduce the M0 GF(2^8) formal diagnosis from the repository root.
set -u -o pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
out="$root/results/m0-gf8-bounded-20260724T203611Z"
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
    local rc=$?
    printf '%s\t%s\n' "$name" "$rc" >>"$out/status.tsv"
    return "$rc"
}

{
    date -u +'%Y-%m-%dT%H:%M:%SZ'
    git rev-parse HEAD
    git status --short
    sby --version
    yosys -V
    yosys-smtbmc -h | head -n 1
    boolector --version
    cvc5 --version | head -n 1
    z3 --version
    timeout --version | head -n 1
} >"$out/versions.log" 2>&1

: >"$out/status.tsv"
# Baseline: preserve the original file, but use a short external wall-time cap.
run baseline-original-cvc5-timeout \
    timeout --foreground 12s bash -lc 'cd formal && sby -f gf8_mul.sby' || true
# Solver/configuration probe: expected to fail immediately because Boolector
# cannot consume the universal quantifier used for the unchanged `anyconst`s.
run depth22-boolector-incompatible \
    timeout --foreground 15s bash -lc 'cd formal && sby -f gf8_mul_bounded_boolector.sby' || true
# Quantifier-capable solver probe: it reaches frame 21 but is externally capped.
run depth22-z3-timeout \
    timeout --foreground 15s bash -lc 'cd formal && sby -f gf8_mul_depth22_z3.sby' || true
# Reliable finite check: SAT asks whether any 22-step counterexample to every
# unchanged assertion exists.  Exit 0 means no such counterexample was found.
run bounded-depth22-yosys-sat \
    timeout --foreground 60s bash -lc 'cd formal && yosys -s gf8_mul_bounded.ys' || true
# Invocation/configuration sanity: elaborate the unchanged formal top.
run formal-elaboration \
    yosys -p 'read_verilog -formal -sv src/gf2n_mul_bitstream.sv formal/gf8_mul_formal.sv; prep -top gf8_mul_formal; check' || true

#!/bin/sh
# LSC1-08 S11 AC-1 driver.
#
# Discharges the dominance obligation for the five static admission predicates
# deleted from the lsc1_packet_frontend decode ladder: each predicate, conjoined
# with the shipped lsc1_request_validator accepting the frame, is UNSAT over the
# whole 1547-bit free input space.  It then discharges five non-vacuity
# obligations showing the proof is capable of failing.
#
# Run from the repository root:
#   sh evidence/lsc1-08-s11/check_validator_dominance.sh
set -e

PROBE=evidence/lsc1-08-s11/dominance_probe.sv
SRC=asic_core/rtl/lsc1_request_validator.sv

# $1 = validator source, $2 = SEL (0 aggregate, 1..5 individual)
prove() {
    yosys -p "read_verilog -sv $1 $PROBE; \
              chparam -set SEL $2 probe_top; \
              prep -top probe_top; flatten; hierarchy -top probe_top; \
              sat -verify -prove-asserts -set-def-inputs"
}

# Byte-exact anchors.  Every perturbation below asserts ALL of them before it
# edits anything, so a perturbation cannot silently become a no-op if the
# validator is refactored.
assert_anchors() {
    test "$(grep -Foc 'end else if (cells_bad) begin' "$1")" -eq 1
    test "$(grep -Foc 'wire bad_proposal = is_jump &&' "$1")" -eq 1
    test "$(grep -Foc 'localparam integer MUL_CELL_3_AT = 77;' "$1")" -eq 1
    test "$(grep -Foc 'localparam integer JUMP_CELL_3_AT = 86;' "$1")" -eq 1
    test "$(grep -Foc 'localparam integer SET_CELL_AT = 34;' "$1")" -eq 1
}

assert_anchors "$SRC"

echo "== AC-1 dominance: shipped validator dominates all five deleted predicates =="
for sel in 0 1 2 3 4 5; do
    case $sel in
        0) name=viol_any ;;
        1) name=viol_set ;;
        2) name=viol_deref ;;
        3) name=viol_jump_cell ;;
        4) name=viol_jump_prop ;;
        5) name=viol_alu ;;
    esac
    prove "$SRC" "$sel" >"/tmp/s11_dominance_$name.log" 2>&1
    grep -Fq "SAT proof finished - no model found: SUCCESS!" "/tmp/s11_dominance_$name.log"
    echo "dominance $name: UNSAT -- SUCCESS"
done

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Each falsifier names the individual obligation it must break.
for perturbation in drop-cells_bad-arm drop-bad_proposal mul-cell3-offset \
                    jump-cell3-offset set-cell-offset; do
    cp "$SRC" "$work/dut.sv"
    assert_anchors "$work/dut.sv"
    case $perturbation in
        drop-cells_bad-arm)
            sel=2; target=viol_deref
            sed -i 's/end else if (cells_bad) begin/end else if (1'"'"'b0) begin/' "$work/dut.sv" ;;
        drop-bad_proposal)
            sel=4; target=viol_jump_prop
            sed -i 's/wire bad_proposal = is_jump \&\&/wire bad_proposal = 1'"'"'b0 \&\& is_jump \&\&/' "$work/dut.sv" ;;
        mul-cell3-offset)
            sel=5; target=viol_alu
            sed -i 's/localparam integer MUL_CELL_3_AT = 77;/localparam integer MUL_CELL_3_AT = 78;/' "$work/dut.sv" ;;
        jump-cell3-offset)
            sel=3; target=viol_jump_cell
            sed -i 's/localparam integer JUMP_CELL_3_AT = 86;/localparam integer JUMP_CELL_3_AT = 85;/' "$work/dut.sv" ;;
        set-cell-offset)
            sel=1; target=viol_set
            sed -i 's/localparam integer SET_CELL_AT = 34;/localparam integer SET_CELL_AT = 35;/' "$work/dut.sv" ;;
    esac
    if cmp -s "$SRC" "$work/dut.sv"; then
        echo "$perturbation perturbation edited nothing" >&2
        exit 1
    fi
    if prove "$work/dut.sv" "$sel" >"$work/$perturbation.log" 2>&1; then
        echo "$perturbation perturbation unexpectedly proved $target dominated" >&2
        exit 1
    fi
    grep -Fq "Called with -verify and proof did fail!" "$work/$perturbation.log"
    echo "non-vacuity $perturbation: $target proof correctly FAILED"
done

echo "PASS: AC-1 dominance proved (aggregate + five individual) and five non-vacuity perturbations rejected"

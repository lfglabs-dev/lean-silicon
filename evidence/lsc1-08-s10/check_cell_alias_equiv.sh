#!/bin/sh
# AC-1 driver: discharges the combinational equivalence obligation between the
# frozen transcription of the base predicate and the shipped
# lsc1_cell_alias_check, then discharges the four non-vacuity obligations that
# show the miter is capable of failing.
#
# Run from the repository root:
#   sh evidence/lsc1-08-s10/check_cell_alias_equiv.sh
set -e

MITER=evidence/lsc1-08-s10/cell_alias_equiv_miter.sv
SRC=asic_core/rtl/lsc1_cell_alias_check.sv

prove() {
    yosys -p "read_verilog -sv $1 $MITER; prep; \
              miter -equiv -flatten -make_assert cell_alias_base cell_alias_head miter; \
              hierarchy -top miter; sat -verify -prove-asserts -set-def-inputs"
}

echo "== AC-1 equivalence: frozen base transcription vs shipped module =="
prove "$SRC" >/tmp/cell_alias_equiv.log 2>&1
grep -Fq "SAT proof finished - no model found: SUCCESS!" /tmp/cell_alias_equiv.log
echo "equivalence: SUCCESS"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

for perturbation in pair_drop deref_base_addend deref_cell_offset scalar_cell_offsets; do
    cp "$SRC" "$work/dut.sv"
    test "$(grep -Foc 'assign alias_inconsistent = checked && (alias_ab || alias_ac || alias_bc);' "$work/dut.sv")" -eq 1
    test "$(grep -Foc 'wire [31:0] address_b = is_deref ? base_index + offset_b : fp + offset_b;' "$work/dut.sv")" -eq 1
    test "$(grep -Foc 'localparam integer DEREF_CELL_1_AT = 47;' "$work/dut.sv")" -eq 1
    test "$(grep -Foc 'localparam integer SCALAR_CELL_1_AT = 43;' "$work/dut.sv")" -eq 1
    test "$(grep -Foc 'localparam integer SCALAR_CELL_2_AT = 60;' "$work/dut.sv")" -eq 1
    case $perturbation in
        pair_drop)
            sed -i 's/assign alias_inconsistent = checked \&\& (alias_ab || alias_ac || alias_bc);/assign alias_inconsistent = checked \&\& (alias_ab || alias_bc);/' "$work/dut.sv" ;;
        deref_base_addend)
            sed -i 's/wire \[31:0\] address_b = is_deref ? base_index + offset_b : fp + offset_b;/wire [31:0] address_b = fp + offset_b;/' "$work/dut.sv" ;;
        deref_cell_offset)
            sed -i 's/localparam integer DEREF_CELL_1_AT = 47;/localparam integer DEREF_CELL_1_AT = 43;/' "$work/dut.sv" ;;
        scalar_cell_offsets)
            sed -i 's/localparam integer SCALAR_CELL_1_AT = 43;/localparam integer SCALAR_CELL_1_AT = 47;/; s/localparam integer SCALAR_CELL_2_AT = 60;/localparam integer SCALAR_CELL_2_AT = 64;/' "$work/dut.sv" ;;
    esac
    if cmp -s "$SRC" "$work/dut.sv"; then
        echo "$perturbation perturbation edited nothing" >&2
        exit 1
    fi
    if prove "$work/dut.sv" >"$work/$perturbation.log" 2>&1; then
        echo "$perturbation perturbation unexpectedly proved equivalent" >&2
        exit 1
    fi
    grep -Fq "Called with -verify and proof did fail!" "$work/$perturbation.log"
    echo "non-vacuity $perturbation: proof correctly FAILED"
done

echo "PASS: AC-1 equivalence proved and four non-vacuity perturbations rejected"

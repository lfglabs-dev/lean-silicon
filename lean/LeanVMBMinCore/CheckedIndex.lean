/-!
Checked host-index arithmetic for the strict scalar profile.

The frozen semantics makes index arithmetic a partial operation: an overflowing
`u32` addition faults before it is used as an address or program counter.  This
module keeps that policy separate from the deliberately simplified ISA model,
so later refinements can share the same executable operation and its basic
proof obligations.
-/

namespace LeanVMBMinCore.CheckedIndex

/-- Host indexes are mathematical naturals until they pass the `u32` bound. -/
abbrev Index := Nat

/-- Largest valid scalar-profile host index. -/
def max : Nat := 2 ^ 32 - 1

/-- Executable validity predicate for a host index. -/
def valid (index : Index) : Prop := index ≤ max

/-- Checked addition used before constructing a local address or next PC. -/
def add (left right : Index) : Option Index :=
  if left + right ≤ max then some (left + right) else none

@[simp] theorem add_eq_some (left right : Index) (h : left + right ≤ max) :
    add left right = some (left + right) := by
  simp [add, h]

@[simp] theorem add_eq_none (left right : Index) (h : max < left + right) :
    add left right = none := by
  simp [add, Nat.not_le_of_lt h]

/-- Successful checked addition returns the mathematical sum. -/
theorem add_some_value {left right result : Index}
    (h : add left right = some result) :
    result = left + right := by
  simp [add] at h
  exact h.2.symm

/-- A successful checked addition establishes validity of its result. -/
theorem add_some_valid {left right result : Index}
    (h : add left right = some result) :
    valid result := by
  simp [add, valid] at h
  change result ≤ max
  rw [← h.2]
  exact h.1

/-- Overflow is exactly the absence of a checked-addition result. -/
theorem add_none_iff {left right : Index} :
    add left right = none ↔ max < left + right := by
  simp [add, Nat.lt_iff_add_one_le]

/-- Adding zero is available for every valid index. -/
theorem add_zero (index : Index) (h : valid index) :
    add index 0 = some index := by
  simpa [valid] using add_eq_some index 0 h

/-- A local-address result is a valid host index. -/
theorem local_result_valid {fp offset address : Index}
    (h : add fp offset = some address) :
    valid address :=
  add_some_valid h

/-- A successful PC increment is exactly one greater than the old PC. -/
theorem next_pc_value {pc next : Index} (h : add pc 1 = some next) :
    next = pc + 1 :=
  add_some_value h

end LeanVMBMinCore.CheckedIndex

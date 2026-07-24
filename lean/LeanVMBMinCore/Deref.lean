import LeanVMBMinCore.Memory

/-!
A simplified but semantically faithful model of `DEREF Cell` reconciliation.
It captures the five cases in the current leanVM-b interpreter without yet
modeling access-count trace columns or the end-of-run deferred fixpoint.
-/

namespace LeanVMBMinCore.Deref

open LeanVMBMinCore.Memory

inductive Result where
  | ok (memory : Mem)
  | deferred (left right : Nat) (memory : Mem)
  | fault

/-- Equate two write-once cells, filling the missing side when possible. -/
def reconcile (m : Mem) (left right : Nat) : Result :=
  let l := m left
  let r := m right
  if l.written then
    if r.written then
      if l.value = r.value then .ok m else .fault
    else
      .ok (writeRaw m right l.value)
  else if r.written then
    .ok (writeRaw m left r.value)
  else
    .deferred left right m

/-- Both written and equal is a no-op. -/
theorem reconcile_both_equal
    (m : Mem) (left right : Nat)
    (hl : (m left).written = true)
    (hr : (m right).written = true)
    (hv : (m left).value = (m right).value) :
    reconcile m left right = .ok m := by
  simp [reconcile, hl, hr, hv]

/-- Both written but unequal is the exact conflict case. -/
theorem reconcile_both_conflict
    (m : Mem) (left right : Nat)
    (hl : (m left).written = true)
    (hr : (m right).written = true)
    (hv : (m left).value ≠ (m right).value) :
    reconcile m left right = .fault := by
  simp [reconcile, hl, hr, hv]

/-- A written left cell fills an unwritten right cell. -/
theorem reconcile_fill_right
    (m : Mem) (left right : Nat)
    (hl : (m left).written = true)
    (hr : (m right).written = false) :
    reconcile m left right = .ok (writeRaw m right (m left).value) := by
  simp [reconcile, hl, hr]

/-- A written right cell fills an unwritten left cell. -/
theorem reconcile_fill_left
    (m : Mem) (left right : Nat)
    (hl : (m left).written = false)
    (hr : (m right).written = true) :
    reconcile m left right = .ok (writeRaw m left (m right).value) := by
  simp [reconcile, hl, hr]

/-- Two unwritten cells produce a deferred equality record. -/
theorem reconcile_deferred
    (m : Mem) (left right : Nat)
    (hl : (m left).written = false)
    (hr : (m right).written = false) :
    reconcile m left right = .deferred left right m := by
  simp [reconcile, hl, hr]

/-- The filled-right result contains the left value at both distinct cells. -/
theorem fill_right_establishes_equality
    (m : Mem) (left right : Nat) (h : left ≠ right) :
    let m' := writeRaw m right (m left).value
    (m' left).value = (m' right).value := by
  simp [writeRaw, h, Ne.symm h]

/-- The filled-left result contains the right value at both distinct cells. -/
theorem fill_left_establishes_equality
    (m : Mem) (left right : Nat) (h : left ≠ right) :
    let m' := writeRaw m left (m right).value
    (m' left).value = (m' right).value := by
  simp [writeRaw, h, Ne.symm h]

end LeanVMBMinCore.Deref

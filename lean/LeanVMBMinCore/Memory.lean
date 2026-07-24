import Std.Tactic.BVDecide

/-!
A small write-once memory model.  It separates the deterministic cell update
from the policy check so the useful update lemmas remain simple.
-/

namespace LeanVMBMinCore.Memory

abbrev Word := BitVec 8

structure Cell where
  written : Bool
  value : Word
  deriving DecidableEq, Repr

abbrev Mem := Nat → Cell

def empty : Mem := fun _ => { written := false, value := 0#8 }

/-- Functional update used after the write-once guard succeeds. -/
def writeRaw (m : Mem) (address : Nat) (value : Word) : Mem :=
  fun query =>
    if query = address then
      { written := true, value := value }
    else
      m query

/-- A write is legal when the cell is fresh or already contains the same value. -/
def compatible (m : Mem) (address : Nat) (value : Word) : Bool :=
  !(m address).written || (m address).value == value

/-- Checked write-once update. -/
def writeOnce (m : Mem) (address : Nat) (value : Word) : Option Mem :=
  if compatible m address value then
    some (writeRaw m address value)
  else
    none

@[simp] theorem read_write_same (m : Mem) (address : Nat) (value : Word) :
    writeRaw m address value address = { written := true, value := value } := by
  simp [writeRaw]

@[simp] theorem read_write_other (m : Mem) (address query : Nat) (value : Word)
    (h : query ≠ address) :
    writeRaw m address value query = m query := by
  simp [writeRaw, h]

theorem writeOnce_fresh (m : Mem) (address : Nat) (value : Word)
    (h : (m address).written = false) :
    writeOnce m address value = some (writeRaw m address value) := by
  simp [writeOnce, compatible, h]

theorem writeOnce_idempotent (m : Mem) (address : Nat) (value : Word)
    (h : (m address).value = value) :
    writeOnce m address value = some (writeRaw m address value) := by
  simp [writeOnce, compatible, h]

theorem writeOnce_conflict (m : Mem) (address : Nat) (value : Word)
    (hw : (m address).written = true)
    (hv : (m address).value ≠ value) :
    writeOnce m address value = none := by
  simp [writeOnce, compatible, hw, hv]

/-- Raw writes to distinct cells commute. -/
theorem writeRaw_commute (m : Mem) (a b : Nat) (va vb : Word) (hab : a ≠ b) :
    writeRaw (writeRaw m a va) b vb =
      writeRaw (writeRaw m b vb) a va := by
  funext q
  by_cases hqa : q = a
  · subst q
    simp [writeRaw, hab]
  · by_cases hqb : q = b
    · subst q
      simp [writeRaw, hqa]
    · simp [writeRaw, hqa, hqb]

end LeanVMBMinCore.Memory

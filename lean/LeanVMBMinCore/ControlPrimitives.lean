import LeanVMBMinCore.CheckedIndex
import LeanVMBMinCore.Deref
import LeanVMBMinCore.GHASH128

/-!
Pure control primitives for the strict-host profile.

The frozen runner uses `u32` operands.  This model accepts signed mathematical
displacements so that both underflow and overflow are explicit failures; every
frozen non-negative operand embeds directly.  Pointer resolution, field
inversion, memory fetch, and instruction fetch remain host responsibilities.
-/

namespace LeanVMBMinCore.ControlPrimitives

open LeanVMBMinCore
open LeanVMBMinCore.Memory

set_option maxRecDepth 10000

abbrev Index := CheckedIndex.Index

/-- A checked signed displacement into the scalar profile's `u32` index space. -/
def checkedOffset (base : Index) (offset : Int) : Option Index :=
  let result := (base : Int) + offset
  if 0 ≤ result ∧ result ≤ (CheckedIndex.max : Int) then
    some result.toNat
  else
    none

@[simp] theorem checkedOffset_zero {base : Index}
    (h : CheckedIndex.valid base) :
    checkedOffset base 0 = some base := by
  simp [checkedOffset, CheckedIndex.valid] at h ⊢
  exact h

@[simp] theorem checkedOffset_negative :
    checkedOffset 0 (-1) = none := by decide

@[simp] theorem checkedOffset_overflow :
    checkedOffset CheckedIndex.max 1 = none := by decide

theorem checkedOffset_some_bounds {base result : Index} {offset : Int}
    (h : checkedOffset base offset = some result) :
    CheckedIndex.valid result := by
  simp only [checkedOffset] at h
  split at h
  next hbounds =>
    simp only [Option.some.injEq] at h
    subst result
    simp only [CheckedIndex.valid]
    exact Int.toNat_le.mpr hbounds.2
  next => contradiction

structure Control where
  pc : Index
  fp : Index
  deriving DecidableEq, Repr

inductive DerefMode where
  | cell
  | pc
  | fp
  deriving DecidableEq, Repr

inductive Fault where
  | address
  | unresolvedPointer
  | writeConflict
  | cellMismatch
  deriving DecidableEq, Repr

inductive DerefResult where
  | ok (control : Control) (memory : Mem)
  | deferred (control : Control) (left right : Index) (memory : Mem)
  | fault (reason : Fault)

def derefEffect (encode : Index → Word) (mode : DerefMode)
    (control : Control) (memory : Mem) (target localAddress nextPc : Index) :
    DerefResult :=
  match mode with
  | .cell =>
      match Deref.reconcile memory target localAddress with
      | .ok memory' => .ok { control with pc := nextPc } memory'
      | .deferred left right memory' =>
          .deferred { control with pc := nextPc } left right memory'
      | .fault => .fault .cellMismatch
  | .pc =>
      match checkedOffset control.pc 2 with
      | none => DerefResult.fault .address
      | some returnPc =>
          match writeOnce memory target (encode returnPc) with
          | some memory' => .ok { control with pc := nextPc } memory'
          | none => .fault .writeConflict
  | .fp =>
      match writeOnce memory target (encode control.fp) with
      | some memory' => .ok { control with pc := nextPc } memory'
      | none => .fault .writeConflict

structure PreparedDeref where
  pointerAddress : Index
  base : Index
  target : Index
  localAddress : Index
  nextPc : Index

/-- Checked address preparation; resolution supplies only `base`, never memory. -/
def prepareDeref (control : Control) (alpha beta gamma : Int)
    (resolvedBase : Option Index) : Option PreparedDeref := do
  let pointerAddress ← checkedOffset control.fp alpha
  let base ← resolvedBase
  let target ← checkedOffset base beta
  let localAddress ← checkedOffset control.fp gamma
  let nextPc ← checkedOffset control.pc 1
  some { pointerAddress, base, target, localAddress, nextPc }

/--
Accept a host-resolved pointer only after re-encoding it, then apply the pure
DEREF effect.  The primitive owns neither a resolver nor dense memory.
-/
def executeDeref (encode : Index → Word) (mode : DerefMode)
    (control : Control) (memory : Mem) (prepared : PreparedDeref) : DerefResult :=
  let pointer := memory prepared.pointerAddress
  if !pointer.written || pointer.value ≠ encode prepared.base then
    .fault .unresolvedPointer
  else
    derefEffect encode mode control memory prepared.target prepared.localAddress
      prepared.nextPc

@[simp] theorem prepareDeref_negative :
    prepareDeref { pc := 4, fp := 0 } 0 (-1) 0 (some 0) = none := by
  decide

theorem executeDeref_deterministic
    (encode : Index → Word) (mode : DerefMode) (control : Control) (memory : Mem)
    (prepared : PreparedDeref) (r₁ r₂ : DerefResult)
    (h₁ : executeDeref encode mode control memory prepared = r₁)
    (h₂ : executeDeref encode mode control memory prepared = r₂) :
    r₁ = r₂ := by
  rw [← h₁, ← h₂]

theorem deref_fp_success {encode : Index → Word} {control : Control}
    {memory memory' : Mem} {target localAddress nextPc : Index}
    (hw : writeOnce memory target (encode control.fp) = some memory') :
    derefEffect encode .fp control memory target localAddress nextPc =
      .ok { control with pc := nextPc } memory' := by
  change
    (match writeOnce memory target (encode control.fp) with
      | some memory' => DerefResult.ok { control with pc := nextPc } memory'
      | none => DerefResult.fault .writeConflict) =
      DerefResult.ok { control with pc := nextPc } memory'
  rw [hw]

theorem writeOnce_success_frame {memory memory' : Mem} {target query : Index}
    {value : Word} (hw : writeOnce memory target value = some memory')
    (hne : query ≠ target) :
    memory' query = memory query := by
  unfold writeOnce at hw
  split at hw
  · cases hw
    exact read_write_other _ _ _ _ hne
  · contradiction

theorem executeDeref_rejects_unwritten_pointer
    (encode : Index → Word) (mode : DerefMode) (control : Control)
    (memory : Mem) (prepared : PreparedDeref)
    (h : (memory prepared.pointerAddress).written = false) :
    executeDeref encode mode control memory prepared =
      .fault .unresolvedPointer := by
  simp [executeDeref, h]

/-! JUMP is a control update only.  It performs no fetch and owns no resolver. -/

inductive JumpResult where
  | ok (control : Control)
  | fault (reason : Fault)
  deriving DecidableEq, Repr

def jump (control : Control) (condition : Word)
    (resolvedTargets : Option (Index × Index)) : JumpResult :=
  if condition = 0#128 then
    match checkedOffset control.pc 1 with
    | some nextPc => .ok { control with pc := nextPc }
    | none => .fault .address
  else
    match resolvedTargets with
    | some (targetPc, targetFp) => .ok { pc := targetPc, fp := targetFp }
    | none => .fault .unresolvedPointer

@[simp] theorem jump_not_taken {control : Control} {nextPc : Index}
    (h : checkedOffset control.pc 1 = some nextPc) :
    jump control 0#128 none = .ok { control with pc := nextPc } := by
  simp [jump, h]

@[simp] theorem jump_taken {control : Control} {condition : Word}
    (hnz : condition ≠ 0#128) (targetPc targetFp : Index) :
    jump control condition (some (targetPc, targetFp)) =
      .ok { pc := targetPc, fp := targetFp } := by
  simp [jump, hnz]

theorem jump_not_taken_preserves_fp {control control' : Control}
    {targets : Option (Index × Index)}
    (h : jump control 0#128 targets = .ok control') :
    control'.fp = control.fp := by
  simp only [jump, ↓reduceIte] at h
  split at h
  next nextPc heq =>
    cases h
    rfl
  next => cases h

theorem jump_deterministic (control : Control) (condition : Word)
    (targets : Option (Index × Index)) (r₁ r₂ : JumpResult)
    (h₁ : jump control condition targets = r₁)
    (h₂ : jump control condition targets = r₂) :
    r₁ = r₂ := by
  rw [← h₁, ← h₂]

/-! Host-proposed inversion witnesses are checked, never computed. -/

def acceptsInverse (value witness : GHASH128.Word) : Bool :=
  value != 0#128 && GHASH128.mul value witness == 1#128

theorem acceptsInverse_sound {value witness : GHASH128.Word}
    (h : acceptsInverse value witness = true) :
    value ≠ 0#128 ∧ GHASH128.mul value witness = 1#128 := by
  simpa [acceptsInverse] using h

@[simp] theorem acceptsInverse_zero_rejected (witness : GHASH128.Word) :
    acceptsInverse 0#128 witness = false := by
  simp [acceptsInverse]

example : acceptsInverse 1#128 1#128 = true := by decide
example : acceptsInverse 0#128 0#128 = false := by decide

end LeanVMBMinCore.ControlPrimitives

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
  if base ≤ CheckedIndex.max ∧
      0 ≤ result ∧ result ≤ (CheckedIndex.max : Int) then
    some result.toNat
  else
    none

@[simp] theorem checkedOffset_zero {base : Index}
    (h : CheckedIndex.valid base) :
    checkedOffset base 0 = some base := by
  have hb : base ≤ CheckedIndex.max := h
  simp [checkedOffset, hb]

@[simp] theorem checkedOffset_negative :
    checkedOffset 0 (-1) = none := by decide

@[simp] theorem checkedOffset_overflow :
    checkedOffset CheckedIndex.max 1 = none := by decide

@[simp] theorem checkedOffset_rejects_invalid_base :
    checkedOffset (CheckedIndex.max + 1) (-1) = none := by decide

theorem checkedOffset_some_bounds {base result : Index} {offset : Int}
    (h : checkedOffset base offset = some result) :
    CheckedIndex.valid result := by
  simp only [checkedOffset] at h
  split at h
  next hbounds =>
    simp only [Option.some.injEq] at h
    subst result
    simp only [CheckedIndex.valid]
    exact Int.toNat_le.mpr hbounds.2.2
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
  | invalidInverse
  | invalidBranch
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

theorem reconcile_success_frame {memory memory' : Mem}
    {target localAddress query : Index}
    (h : Deref.reconcile memory target localAddress = .ok memory')
    (ht : query ≠ target) (hl : query ≠ localAddress) :
    memory' query = memory query := by
  by_cases htw : (memory target).written = true
  · by_cases hlw : (memory localAddress).written = true
    · by_cases hv : (memory target).value = (memory localAddress).value
      · simp [Deref.reconcile, htw, hlw, hv] at h
        subst memory'
        rfl
      · simp [Deref.reconcile, htw, hlw, hv] at h
    · have hlwf : (memory localAddress).written = false := by
        exact Bool.eq_false_iff.mpr hlw
      simp [Deref.reconcile, htw, hlwf] at h
      subst memory'
      exact read_write_other _ _ _ _ hl
  · have htwf : (memory target).written = false := by
      exact Bool.eq_false_iff.mpr htw
    by_cases hlw : (memory localAddress).written = true
    · simp [Deref.reconcile, htwf, hlw] at h
      subst memory'
      exact read_write_other _ _ _ _ ht
    · have hlwf : (memory localAddress).written = false := by
        exact Bool.eq_false_iff.mpr hlw
      simp [Deref.reconcile, htwf, hlwf] at h

theorem derefEffect_success_frame {encode : Index → Word} {mode : DerefMode}
    {control control' : Control} {memory memory' : Mem}
    {target localAddress nextPc query : Index}
    (h : derefEffect encode mode control memory target localAddress nextPc =
      .ok control' memory')
    (ht : query ≠ target) (hl : query ≠ localAddress) :
    memory' query = memory query := by
  cases mode with
  | cell =>
      simp only [derefEffect] at h
      split at h
      · cases h
        exact reconcile_success_frame ‹_› ht hl
      · contradiction
      · contradiction
  | pc =>
      simp only [derefEffect] at h
      split at h
      · contradiction
      · split at h
        · cases h
          exact writeOnce_success_frame ‹_› ht
        · contradiction
  | fp =>
      simp only [derefEffect] at h
      split at h
      · cases h
        exact writeOnce_success_frame ‹_› ht
      · contradiction

theorem executeDeref_success_frame {encode : Index → Word} {mode : DerefMode}
    {control control' : Control} {memory memory' : Mem}
    {prepared : PreparedDeref} {query : Index}
    (h : executeDeref encode mode control memory prepared =
      .ok control' memory')
    (ht : query ≠ prepared.target) (hl : query ≠ prepared.localAddress) :
    memory' query = memory query := by
  simp only [executeDeref] at h
  split at h
  · contradiction
  · exact derefEffect_success_frame h ht hl

/-! JUMP is a control update only.  It performs no fetch and owns no resolver. -/

/-- A host inverse proposal is valid only for a nonzero value and product one. -/
def acceptsInverse (value witness : GHASH128.Word) : Bool :=
  value != 0#128 && GHASH128.mul value witness == 1#128

inductive JumpResult where
  | ok (control : Control)
  | fault (reason : Fault)
  deriving DecidableEq, Repr

def jump (encode : Index → Word) (control : Control) (condition : Word)
    (targetPcWord targetFpWord inverseWitness : Word)
    (resolvedTargets : Option (Index × Index)) : JumpResult :=
  if condition = 0#128 then
    match resolvedTargets with
    | some _ => .fault .invalidBranch
    | none =>
        if inverseWitness = 0#128 then
          match checkedOffset control.pc 1 with
          | some nextPc => .ok { control with pc := nextPc }
          | none => .fault .address
        else
          .fault .invalidInverse
  else
    if acceptsInverse condition inverseWitness then
      match resolvedTargets with
      | some (targetPc, targetFp) =>
          if targetPc ≤ CheckedIndex.max ∧ targetFp ≤ CheckedIndex.max ∧
              encode targetPc = targetPcWord ∧ encode targetFp = targetFpWord then
            .ok { pc := targetPc, fp := targetFp }
          else
            .fault .unresolvedPointer
      | none => .fault .unresolvedPointer
    else
      .fault .invalidInverse

@[simp] theorem jump_not_taken {encode : Index → Word} {control : Control}
    {nextPc : Index} {targetPcWord targetFpWord : Word}
    (h : checkedOffset control.pc 1 = some nextPc) :
    jump encode control 0#128 targetPcWord targetFpWord 0#128 none =
      .ok { control with pc := nextPc } := by
  simp [jump, h]

@[simp] theorem jump_not_taken_rejects_targets {encode : Index → Word}
    {control : Control} {targetPcWord targetFpWord : Word}
    (targetPc targetFp : Index) :
    jump encode control 0#128 targetPcWord targetFpWord 0#128
      (some (targetPc, targetFp)) = .fault .invalidBranch := by
  simp [jump]

@[simp] theorem jump_taken {encode : Index → Word} {control : Control}
    {condition : Word} (hnz : condition ≠ 0#128) (targetPc targetFp : Index)
    (inverseWitness : Word)
    (hinv : acceptsInverse condition inverseWitness = true)
    (hpc : CheckedIndex.valid targetPc) (hfp : CheckedIndex.valid targetFp) :
    jump encode control condition (encode targetPc) (encode targetFp)
      inverseWitness
      (some (targetPc, targetFp)) =
      .ok { pc := targetPc, fp := targetFp } := by
  have hpc' : targetPc ≤ CheckedIndex.max := hpc
  have hfp' : targetFp ≤ CheckedIndex.max := hfp
  simp [jump, hnz, hinv, hpc', hfp']

@[simp] theorem jump_rejects_bad_inverse {encode : Index → Word}
    {control : Control} {condition : Word} (hnz : condition ≠ 0#128)
    {targetPc targetFp : Index} {targetPcWord targetFpWord inverseWitness : Word}
    (hinv : acceptsInverse condition inverseWitness = false) :
    jump encode control condition targetPcWord targetFpWord inverseWitness
      (some (targetPc, targetFp)) = .fault .invalidInverse := by
  simp [jump, hnz, hinv]

@[simp] theorem jump_rejects_bad_target {encode : Index → Word}
    {control : Control} {condition : Word} (hnz : condition ≠ 0#128)
    {targetPc targetFp : Index} {targetPcWord targetFpWord inverseWitness : Word}
    (hinv : acceptsInverse condition inverseWitness = true)
    (hbad : encode targetPc ≠ targetPcWord ∨ encode targetFp ≠ targetFpWord) :
    jump encode control condition targetPcWord targetFpWord inverseWitness
      (some (targetPc, targetFp)) = .fault .unresolvedPointer := by
  rcases hbad with hbad | hbad
  · simp [jump, hnz, hinv, hbad]
  · simp [jump, hnz, hinv, hbad]

theorem jump_not_taken_preserves_fp {encode : Index → Word}
    {control control' : Control} {targetPcWord targetFpWord : Word}
    {targets : Option (Index × Index)}
    (h : jump encode control 0#128 targetPcWord targetFpWord 0#128 targets =
      .ok control') :
    control'.fp = control.fp := by
  cases targets with
  | some targets => simp [jump] at h
  | none =>
      simp only [jump, ↓reduceIte, ↓reduceIte] at h
      split at h
      next nextPc heq =>
        cases h
        rfl
      next => cases h

theorem jump_deterministic (encode : Index → Word) (control : Control)
    (condition targetPcWord targetFpWord inverseWitness : Word)
    (targets : Option (Index × Index)) (r₁ r₂ : JumpResult)
    (h₁ : jump encode control condition targetPcWord targetFpWord inverseWitness
      targets = r₁)
    (h₂ : jump encode control condition targetPcWord targetFpWord inverseWitness
      targets = r₂) :
    r₁ = r₂ := by
  rw [← h₁, ← h₂]

/-! Host-proposed inversion witnesses are checked, never computed. -/

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

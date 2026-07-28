/-!
Pure functional model of the non-service LSC-1 transaction lifecycle.

Instruction semantics supply a proposed `Transition`; this module owns only
staging, matching retirement, abort, reset, and committed architectural state.
That separation is the stable seam for later arithmetic, DEREF/JUMP, and
RETIRE refinement lanes.
-/

namespace LeanVMBMinCore.Transaction

abbrev TxnId := UInt32
abbrev Index := UInt32
abbrev ResultChecksum := UInt32
def indexLimit : Nat := 2 ^ 16

structure Committed where
  pc : Index
  fp : Index
  retireSeq : UInt32
  deriving DecidableEq, Repr

structure Transition where
  txnId : TxnId
  currentPc : Index
  currentFp : Index
  nextPc : Index
  nextFp : Index
  resultChecksum : ResultChecksum
  deriving DecidableEq, Repr

inductive TxnState where
  | idle
  | resultPending (transition : Transition)
  deriving DecidableEq, Repr

structure Model where
  committed : Committed
  stateValid : Bool
  state : TxnState
  deriving DecidableEq, Repr

inductive Fault where
  | badState
  | indexRange
  | stateMismatch
  | retireMismatch
  deriving DecidableEq, Repr

inductive Command where
  | stage (transition : Transition)
  | retire (txnId : TxnId) (resultChecksum : ResultChecksum)
  | abort
  | reset
  deriving DecidableEq, Repr

structure Outcome where
  model : Model
  fault : Option Fault := none
  retired : Bool := false
  deriving DecidableEq, Repr

def initial : Model := {
  committed := { pc := 0, fp := 0, retireSeq := 0 }
  stateValid := false
  state := .idle
}

def stateMatches (model : Model) (transition : Transition) : Bool :=
  !model.stateValid ||
    (transition.currentPc == model.committed.pc &&
      transition.currentFp == model.committed.fp)

def currentIndicesInRange (transition : Transition) : Bool :=
  decide (transition.currentPc.toNat < indexLimit) &&
    decide (transition.currentFp.toNat < indexLimit)

def step (model : Model) (command : Command) : Outcome :=
  match command with
  | .reset => { model := initial }
  | .abort => { model := { model with state := .idle } }
  | .stage transition =>
      match model.state with
      | .resultPending _ => { model := model, fault := some .badState }
      | .idle =>
          if !stateMatches model transition then
            { model := model, fault := some .stateMismatch }
          else if !currentIndicesInRange transition then
            { model := model, fault := some .indexRange }
          else
            { model := { model with state := .resultPending transition } }
  | .retire txnId resultChecksum =>
      match model.state with
      | .idle => { model := model, fault := some .badState }
      | .resultPending transition =>
          if transition.txnId == txnId &&
              transition.resultChecksum == resultChecksum then
            let committed := {
              pc := transition.nextPc
              fp := transition.nextFp
              retireSeq := model.committed.retireSeq + 1
            }
            {
              model := { committed := committed, stateValid := true, state := .idle }
              retired := true
            }
          else
            {
              model := { model with state := .idle }
              fault := some .retireMismatch
            }

@[simp] theorem stage_is_atomic (model : Model) (transition : Transition)
    (hidle : model.state = .idle)
    (hrange : currentIndicesInRange transition = true)
    (hmatch : stateMatches model transition = true) :
    step model (.stage transition) =
      { model := { model with state := .resultPending transition } } := by
  simp [step, hidle, hrange, hmatch]

@[simp] theorem out_of_range_stage_is_rejected (model : Model)
    (transition : Transition) (hidle : model.state = .idle)
    (hmatch : stateMatches model transition = true)
    (hrange : currentIndicesInRange transition = false) :
    step model (.stage transition) =
      { model := model, fault := some .indexRange } := by
  simp [step, hidle, hmatch, hrange]

@[simp] theorem state_mismatch_precedes_index_range (model : Model)
    (transition : Transition) (hidle : model.state = .idle)
    (hmatch : stateMatches model transition = false) :
    step model (.stage transition) =
      { model := model, fault := some .stateMismatch } := by
  simp [step, hidle, hmatch]

@[simp] theorem abort_preserves_committed (model : Model) :
    (step model .abort).model.committed = model.committed := by
  rfl

@[simp] theorem abort_clears_pending (model : Model) :
    (step model .abort).model.state = .idle := by
  rfl

@[simp] theorem matching_retire_commits (model : Model) (transition : Transition) :
    let outcome := step { model with state := .resultPending transition }
      (.retire transition.txnId transition.resultChecksum)
    outcome.model.committed.pc = transition.nextPc ∧
      outcome.model.committed.fp = transition.nextFp ∧
      outcome.model.committed.retireSeq = model.committed.retireSeq + 1 ∧
      outcome.model.state = .idle ∧ outcome.retired = true := by
  simp [step]

@[simp] theorem matching_retire_is_exactly_once (model : Model)
    (transition : Transition) :
    let first := step { model with state := .resultPending transition }
      (.retire transition.txnId transition.resultChecksum)
    let second := step first.model
      (.retire transition.txnId transition.resultChecksum)
    first.retired = true ∧ second.retired = false ∧
      second.fault = some .badState ∧
      second.model.committed = first.model.committed := by
  simp [step]

@[simp] theorem mismatched_retire_does_not_commit (model : Model)
    (transition : Transition) (txnId : TxnId) (checksum : ResultChecksum)
    (hmismatch : transition.txnId ≠ txnId ∨
      transition.resultChecksum ≠ checksum) :
    let outcome := step { model with state := .resultPending transition }
      (.retire txnId checksum)
    outcome.model.committed = model.committed ∧
      outcome.model.state = .idle ∧
      outcome.fault = some .retireMismatch ∧ outcome.retired = false := by
  rcases hmismatch with hid | hchecksum
  · simp [step, hid]
  · simp [step, hchecksum]

@[simp] theorem reset_restores_initial (model : Model) :
    (step model .reset).model = initial := by
  rfl

def exampleTransition : Transition := {
  txnId := 7
  currentPc := 10
  currentFp := 20
  nextPc := 11
  nextFp := 20
  resultChecksum := 0x1234
}

example :
    let staged := step initial (.stage exampleTransition)
    let retired := step staged.model
      (.retire exampleTransition.txnId exampleTransition.resultChecksum)
    retired.model.committed.pc = 11 ∧ retired.model.committed.retireSeq = 1 ∧
      retired.retired = true := by
  decide

example :
    let staged := step initial (.stage exampleTransition)
    (step staged.model .abort).model.committed = initial.committed ∧
      (step staged.model .abort).model.state = .idle := by
  decide

end LeanVMBMinCore.Transaction

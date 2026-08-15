import LeanVMBMinCore.AcceptedSequence
import LeanVMBMinCore.Blake3ServiceLifecycle

/-!
# Finite authored-RTL trace relation

This module defines the Lean side of the finite observation relation.  It does
not contain an executable list of alleged RTL observations.  The gate generates
a separate Lean module whose `rtlFacts` value was decoded from bytes and signal
events emitted by an Icarus run of the authored packet RTL, then asks Lean to
construct `ContractEvidence rtlFacts` from fact equality and semantic premises.
-/

namespace LeanVMBMinCore.AuthoredRTLContract

open LeanVMBMinCore

inductive Operation where
  | set | xor | mul | deref | jump | blake3
  deriving DecidableEq, Repr

inductive Observation where
  | result | serviceRequired | fault | rxStall | txStall
  | resetDiscard | abortDiscard | retire
  deriving DecidableEq, Repr

abbrev Fact := Operation × Observation

private def scalarRequired (op : Operation) : List Fact :=
  [.result, .rxStall, .txStall, .retire].map (op, ·)

private def controlRequired (op : Operation) : List Fact :=
  [.result, .fault, .rxStall, .txStall, .retire].map (op, ·)

/-- The sole normative finite relation.  The left argument supplied by the
generated checker is derived from authored-RTL trace records, never populated
from this value by the Python runner. -/
def requiredFacts : List Fact :=
  scalarRequired .set ++ scalarRequired .xor ++ scalarRequired .mul ++
  controlRequired .deref ++ controlRequired .jump ++
  [.serviceRequired, .result, .fault, .rxStall, .txStall,
   .resetDiscard, .abortDiscard, .retire].map (.blake3, ·)

def factsMatch (rtlFacts : List Fact) : Bool :=
  requiredFacts.all rtlFacts.contains && rtlFacts.all requiredFacts.contains

theorem required_scope_is_exact : factsMatch requiredFacts = true := by decide

/- These names attach the relation's semantic classes to canonical executable
Lean witnesses; they are not an alternate instruction semantics. -/
def set_semantics_reachable := AcceptedScalar.set_decision_reachable
def xor_semantics_reachable := AcceptedScalar.xor_decision_reachable
def mul_semantics_reachable := AcceptedScalar.mul_decision_reachable
def deref_semantics_reachable := AcceptedDeref.accepted_effect_binding_reachable
def jump_semantics_reachable := AcceptedJump.accepted_effect_binding_reachable
theorem blake3_semantics_reachable :
    (FullProfile.prepareBlake3 FullProfile.witnessRawBlake3).isOk := by
  set_option maxRecDepth 10000 in decide

def result_retire_semantics := AcceptedSequence.complete_retires_once
def result_replay_semantics := AcceptedSequence.duplicate_retire_rejected
def abort_semantics := Transaction.abort_clears_pending
def reset_semantics := Transaction.reset_restores_initial
def blake3_retire_semantics := Blake3ServiceLifecycle.retirement_exactly_once

abbrev SetSemantic : Prop := (AcceptedScalar.accept
    (AcceptedScalar.wire 0x03 AcceptedScalar.setBytes)).map
    AcceptedScalar.decision = .ok (.result AcceptedScalar.witnessSetEffect)
abbrev XorSemantic : Prop := (AcceptedScalar.accept
    (AcceptedScalar.wire 0x01 (AcceptedScalar.binaryBytes 52 false))).map
    AcceptedScalar.decision =
    .ok (.result (AcceptedScalar.witnessBinaryEffect 52 38))
abbrev MulSemantic : Prop := (AcceptedScalar.accept
    (AcceptedScalar.wire 0x02 (AcceptedScalar.binaryBytes 1 true))).map
    AcceptedScalar.decision =
    .ok (.result (AcceptedScalar.witnessBinaryEffect 1 18))
abbrev DerefSemantic : Prop := (AcceptedDeref.accept
    (AcceptedDeref.witnessWire 0x04 FullProfile.Payload.witnessDerefBytes)).map
    AcceptedDeref.decision = .ok (.result AcceptedDeref.witnessEffect)
abbrev JumpSemantic : Prop := (AcceptedJump.accept
    (AcceptedJump.witnessWire AcceptedJump.witnessTakenBytes)).map
    AcceptedJump.decision = .ok (.result AcceptedJump.witnessEffect)
abbrev Blake3Semantic : Prop :=
    (FullProfile.prepareBlake3 FullProfile.witnessRawBlake3).isOk
abbrev AbortSemantic : Prop := ∀ model : Transaction.Model,
    (Transaction.step model .abort).model.state = .idle
abbrev ResetSemantic : Prop := ∀ model : Transaction.Model,
    (Transaction.step model .reset).model = Transaction.initial
abbrev RetireSemantic : Prop := ∀
    (model : Transaction.Model) (item : AcceptedSequence.Item),
    model.state = .idle →
    Transaction.currentIndicesInRange (AcceptedSequence.transition item) = true →
    Transaction.stateMatches model (AcceptedSequence.transition item) = true →
    let outcome := AcceptedSequence.complete model item
    outcome.retired = true ∧ outcome.fault = none ∧
      outcome.model.state = .idle ∧
      outcome.model.committed.pc = (AcceptedSequence.transition item).nextPc ∧
      outcome.model.committed.fp = (AcceptedSequence.transition item).nextFp ∧
      outcome.model.committed.retireSeq = model.committed.retireSeq + 1
abbrev Blake3RetireSemantic : Prop := ∀
    (state : FullProfile.EndpointState) (nextServiceId : UInt32)
    (pending : FullProfile.ServicePending)
    (response : FullProfile.Blake3Response) (effect : FullProfile.Effect),
    state.service = .pending nextServiceId pending →
    FullProfile.serviceResponseMatches pending response = true →
    FullProfile.finishBlake3 pending response = .result effect →
    FullProfile.representableB effect = true →
    state.transaction.state = .idle →
    Transaction.currentIndicesInRange (FullProfile.transitionOf effect) = true →
    Transaction.stateMatches state.transaction (FullProfile.transitionOf effect) = true →
    let responded := FullProfile.endpointStep state
      (.service (.respond response))
    let first := FullProfile.endpointStep responded.state
      (.retire effect.common.txnId (FullProfile.effectResultChecksum effect))
    let second := FullProfile.endpointStep first.state
      (.retire effect.common.txnId (FullProfile.effectResultChecksum effect))
    first.transactionOutcome.map (fun o => o.retired) = some true ∧
      second.transactionOutcome.map (fun o => o.retired) = some false ∧
      second.transactionOutcome.bind (fun o => o.fault) = some .badState

/-- A successful certificate contains both exact RTL-derived facts and the
canonical Lean semantic premises.  In particular, list equality alone is not a
proof of this proposition. -/
structure ContractEvidence (rtlFacts : List Fact) : Prop where
  factsExact : factsMatch rtlFacts = true
  setSemantic : SetSemantic
  xorSemantic : XorSemantic
  mulSemantic : MulSemantic
  derefSemantic : DerefSemantic
  jumpSemantic : JumpSemantic
  blake3Semantic : Blake3Semantic
  abortSemantic : AbortSemantic
  resetSemantic : ResetSemantic
  retireSemantic : RetireSemantic
  blake3RetireSemantic : Blake3RetireSemantic

/-- The bounded common-relation theorem.  Every semantic argument is an
explicit premise supplied by the generated checker. -/
theorem contractHolds (rtlFacts : List Fact)
    (hFacts : factsMatch rtlFacts = true)
    (hSet : SetSemantic) (hXor : XorSemantic) (hMul : MulSemantic)
    (hDeref : DerefSemantic) (hJump : JumpSemantic)
    (hBlake3 : Blake3Semantic) (hAbort : AbortSemantic)
    (hReset : ResetSemantic) (hRetire : RetireSemantic)
    (hBlake3Retire : Blake3RetireSemantic) :
    ContractEvidence rtlFacts :=
  ⟨hFacts, hSet, hXor, hMul, hDeref, hJump, hBlake3,
   hAbort, hReset, hRetire, hBlake3Retire⟩

#print axioms required_scope_is_exact
#print axioms set_semantics_reachable
#print axioms blake3_semantics_reachable

end LeanVMBMinCore.AuthoredRTLContract

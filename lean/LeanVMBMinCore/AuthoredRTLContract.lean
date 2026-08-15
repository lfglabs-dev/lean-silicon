import LeanVMBMinCore.AcceptedSequence
import LeanVMBMinCore.Blake3ServiceLifecycle

/-!
# Finite authored-RTL trace relation

This module defines the Lean side of the finite observation relation.  It does
not contain an executable list of alleged RTL observations.  The gate generates
a separate Lean module whose `rtlFacts` value was decoded from bytes and signal
events emitted by an Icarus run of the authored packet RTL, then asks Lean to
decide `contractHolds rtlFacts`.
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

def contractHolds (rtlFacts : List Fact) : Bool :=
  requiredFacts.all rtlFacts.contains && rtlFacts.all requiredFacts.contains

theorem required_scope_is_exact : contractHolds requiredFacts := by decide

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

#print axioms required_scope_is_exact
#print axioms set_semantics_reachable
#print axioms blake3_semantics_reachable

end LeanVMBMinCore.AuthoredRTLContract

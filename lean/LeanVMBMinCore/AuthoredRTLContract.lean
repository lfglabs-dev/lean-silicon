import LeanVMBMinCore.AcceptedSequence
import LeanVMBMinCore.Blake3ServiceLifecycle

/-!
# Observable contract exercised against the authored full LSC-1 RTL

This module names the finite, executable observation alphabet used by
`tools/lsc1_authored_rtl_contract.py`.  The witnesses are deliberately built
from the existing accepted-frame and service-lifecycle models; this is not a
second instruction semantics and it is not an unbounded SV equivalence proof.
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

structure Scenario where
  name : String
  operation : Operation
  observations : List Observation
  deriving Repr

def scenarios : List Scenario := [
  { name := "set", operation := .set,
    observations := [.result, .rxStall, .txStall, .retire] },
  { name := "xor", operation := .xor,
    observations := [.result, .rxStall, .txStall, .retire] },
  { name := "mul", operation := .mul,
    observations := [.result, .rxStall, .txStall, .retire] },
  { name := "deref", operation := .deref,
    observations := [.result, .fault, .rxStall, .txStall, .retire] },
  { name := "jump", operation := .jump,
    observations := [.result, .fault, .rxStall, .txStall, .retire] },
  { name := "blake3", operation := .blake3,
    observations := [.serviceRequired, .result, .fault, .rxStall, .txStall,
      .resetDiscard, .abortDiscard, .retire] }
]

def hasOperation (operation : Operation) : Bool :=
  scenarios.any (fun scenario => scenario.operation == operation)

def hasObservation (observation : Observation) : Bool :=
  scenarios.any (fun scenario => scenario.observations.contains observation)

/-- The executable suite cannot silently narrow any implemented opcode class. -/
theorem operation_scope_complete :
    hasOperation .set && hasOperation .xor && hasOperation .mul &&
    hasOperation .deref && hasOperation .jump && hasOperation .blake3 := by decide

/-- The suite cannot silently drop any observable lifecycle class. -/
theorem observation_scope_complete :
    hasObservation .result && hasObservation .serviceRequired &&
    hasObservation .fault && hasObservation .rxStall &&
    hasObservation .txStall && hasObservation .resetDiscard &&
    hasObservation .abortDiscard && hasObservation .retire := by decide

/- These aliases keep the suite attached to the canonical executable witnesses,
instead of merely asserting membership in the table above. -/
def set_semantics_reachable := AcceptedScalar.set_decision_reachable
def xor_semantics_reachable := AcceptedScalar.xor_decision_reachable
def mul_semantics_reachable := AcceptedScalar.mul_decision_reachable
def deref_semantics_reachable := AcceptedDeref.accepted_effect_binding_reachable
def jump_semantics_reachable := AcceptedJump.accepted_effect_binding_reachable
theorem blake3_semantics_reachable :
    (FullProfile.prepareBlake3 FullProfile.witnessRawBlake3).isOk := by native_decide

def result_retire_semantics := AcceptedSequence.complete_retires_once
def result_replay_semantics := AcceptedSequence.duplicate_retire_rejected
def abort_semantics := Transaction.abort_clears_pending
def reset_semantics := Transaction.reset_restores_initial
def blake3_retire_semantics := Blake3ServiceLifecycle.retirement_exactly_once

def operationName : Operation -> String
  | .set => "SET" | .xor => "XOR" | .mul => "MUL"
  | .deref => "DEREF" | .jump => "JUMP" | .blake3 => "BLAKE3"

def observationName : Observation -> String
  | .result => "RESULT" | .serviceRequired => "SERVICE_REQUIRED"
  | .fault => "FAULT" | .rxStall => "RX_STALL" | .txStall => "TX_STALL"
  | .resetDiscard => "RESET_DISCARD" | .abortDiscard => "ABORT_DISCARD"
  | .retire => "RETIRE"

def contractLines : List String := scenarios.flatMap fun scenario =>
  scenario.observations.map fun observation =>
    s!"CONTRACT {operationName scenario.operation} {observationName observation}"

def main : IO Unit := contractLines.forM IO.println

#eval contractLines.forM IO.println

#print axioms operation_scope_complete
#print axioms observation_scope_complete
#print axioms set_semantics_reachable
#print axioms blake3_semantics_reachable

end LeanVMBMinCore.AuthoredRTLContract

import LeanVMBMinCore.AcceptedDeref
import LeanVMBMinCore.AcceptedJump
import LeanVMBMinCore.AcceptedScalar

/-!
Arbitrary finite mixed-operation sequencing at the accepted packet boundary.

This module composes the existing opcode-specific acceptance/decision bridges
with the transaction model.  It deliberately does not claim that Lean imports
or proves the SystemVerilog implementation.
-/

namespace LeanVMBMinCore.AcceptedSequence

open LeanVMBMinCore
open LeanVMBMinCore.FullProfile

inductive Operation where
  | deref | jump | set | xor | mul
  deriving DecidableEq, Repr

/-- One arbitrary successfully accepted operation, including its exact effect. -/
structure Item where
  operation : Operation
  wire : Packet.RequestWire
  effect : Effect
  accepted : match operation with
    | .deref => ∃ accepted, AcceptedDeref.accept wire = .ok accepted ∧
        AcceptedDeref.decision accepted = .result effect
    | .jump => ∃ accepted, AcceptedJump.accept wire = .ok accepted ∧
        AcceptedJump.decision accepted = .result effect
    | .set => ∃ accepted, accepted.operation = .set ∧
        AcceptedScalar.accept wire = .ok accepted ∧
        AcceptedScalar.decision accepted = .result effect
    | .xor => ∃ accepted, accepted.operation = .xor ∧
        AcceptedScalar.accept wire = .ok accepted ∧
        AcceptedScalar.decision accepted = .result effect
    | .mul => ∃ accepted, accepted.operation = .mul ∧
        AcceptedScalar.accept wire = .ok accepted ∧
        AcceptedScalar.decision accepted = .result effect
  payloadBound : (effectResultPayload effect).length ≤ Packet.maxPayloadBytes

def transition (item : Item) : Transaction.Transition := transitionOf item.effect

def resultResponse (item : Item) : Packet.Response :=
  { status := 0, payload := effectResultPayload item.effect }

def resultWire (item : Item) : Packet.ResponseWire :=
  Packet.encodeResponse crc32 (resultResponse item)

/-- A receipt is emitted only by a successful matching RETIRE. -/
structure Receipt where
  operation : Operation
  txnId : UInt32
  result : Packet.ResponseWire
  retireSeq : UInt32
  deriving DecidableEq, Repr

def receipt (model : Transaction.Model) (item : Item) : Receipt := {
  operation := item.operation
  txnId := (transition item).txnId
  result := resultWire item
  retireSeq := model.committed.retireSeq + 1
}

def complete (model : Transaction.Model) (item : Item) : Transaction.Outcome :=
  let staged := Transaction.step model (.stage (transition item))
  Transaction.step staged.model
    (.retire (transition item).txnId (transition item).resultChecksum)

/-- Legal traffic is state-dependent: each accepted operation starts idle and
matches the committed state and v1 index bound left by its predecessor. -/
def Legal : Transaction.Model → List Item → Prop
  | model, [] => model.state = .idle
  | model, item :: rest =>
      model.state = .idle ∧
      Representable item.effect ∧
      Transaction.currentIndicesInRange (transition item) = true ∧
      Transaction.stateMatches model (transition item) = true ∧
      Legal (complete model item).model rest

def run : Transaction.Model → List Item → Transaction.Model × List Receipt
  | model, [] => (model, [])
  | model, item :: rest =>
      let outcome := complete model item
      let tail := run outcome.model rest
      (tail.1, if outcome.retired then receipt model item :: tail.2 else tail.2)

def expectedReceipts : Transaction.Model → List Item → List Receipt
  | _, [] => []
  | model, item :: rest =>
      receipt model item :: expectedReceipts (complete model item).model rest

/-- The RESULT envelope decodes to the exact effect bytes and its CRC is taken
over those same bytes, for every accepted item in every opcode family. -/
theorem result_wire_byte_exact (item : Item) :
    Packet.decodeResponse crc32 (resultWire item) = .ok (resultResponse item) := by
  exact Packet.decode_encode_response crc32 (resultResponse item) item.payloadBound

theorem complete_retires_once (model : Transaction.Model) (item : Item)
    (hidle : model.state = .idle)
    (hrange : Transaction.currentIndicesInRange (transition item) = true)
    (hmatch : Transaction.stateMatches model (transition item) = true) :
    let outcome := complete model item
    outcome.retired = true ∧ outcome.fault = none ∧
      outcome.model.state = .idle ∧
      outcome.model.committed.pc = (transition item).nextPc ∧
      outcome.model.committed.fp = (transition item).nextFp ∧
      outcome.model.committed.retireSeq = model.committed.retireSeq + 1 := by
  simp only [complete]
  rw [Transaction.stage_is_atomic model (transition item) hidle hrange hmatch]
  simp [Transaction.step]

/-- Replaying the matching RETIRE after completion cannot duplicate a commit. -/
theorem duplicate_retire_rejected (model : Transaction.Model) (item : Item)
    (hidle : model.state = .idle)
    (hrange : Transaction.currentIndicesInRange (transition item) = true)
    (hmatch : Transaction.stateMatches model (transition item) = true) :
    let first := complete model item
    let duplicate := Transaction.step first.model
      (.retire (transition item).txnId (transition item).resultChecksum)
    duplicate.retired = false ∧ duplicate.fault = some .badState ∧
      duplicate.model.committed = first.model.committed := by
  simp only [complete]
  rw [Transaction.stage_is_atomic model (transition item) hidle hrange hmatch]
  simp [Transaction.step]

/-- Arbitrary finite mixed legal sequences have one ordered receipt per
accepted operation, no loss, no duplication, and finish with no pending work. -/
theorem legal_sequence_exact (model : Transaction.Model) (items : List Item)
    (hlegal : Legal model items) :
    (run model items).2 = expectedReceipts model items := by
  induction items generalizing model with
  | nil => rfl
  | cons item rest ih =>
      rcases hlegal with ⟨hidle, _, hrange, hmatch, hrest⟩
      have hcomplete := complete_retires_once model item hidle hrange hmatch
      have hretired : (complete model item).retired = true := hcomplete.1
      simp only [run, expectedReceipts, hretired, if_true, List.cons.injEq, true_and]
      exact ih (model := (complete model item).model) hrest

theorem legal_sequence_no_loss (model : Transaction.Model) (items : List Item)
    (hlegal : Legal model items) :
    (run model items).2.length = items.length := by
  rw [legal_sequence_exact model items hlegal]
  induction items generalizing model with
  | nil => rfl
  | cons item rest ih =>
      rcases hlegal with ⟨_, _, _, _, hrest⟩
      simpa [expectedReceipts] using
        congrArg Nat.succ (ih (model := (complete model item).model) hrest)

theorem legal_sequence_finishes_idle (model : Transaction.Model) (items : List Item)
    (hlegal : Legal model items) : (run model items).1.state = .idle := by
  induction items generalizing model with
  | nil => exact hlegal
  | cons item rest ih =>
      rcases hlegal with ⟨_, _, _, _, hrest⟩
      exact ih (model := (complete model item).model) hrest

/-- Every item admitted by `Legal` stays within the v1 current and next
control-index boundary used by the opcode-specific lifecycle bridges. -/
theorem legal_sequence_representable (model : Transaction.Model) (items : List Item)
    (hlegal : Legal model items) : ∀ item ∈ items, Representable item.effect := by
  intro candidate hmember
  induction items generalizing model with
  | nil => simp at hmember
  | cons item rest ih =>
      rcases hlegal with ⟨_, hrepresentable, _, _, hrest⟩
      simp only [List.mem_cons] at hmember
      rcases hmember with rfl | hmember
      · exact hrepresentable
      · exact ih (model := (complete model item).model) hrest hmember

#print axioms result_wire_byte_exact
#print axioms complete_retires_once
#print axioms duplicate_retire_rejected
#print axioms legal_sequence_exact
#print axioms legal_sequence_no_loss
#print axioms legal_sequence_finishes_idle
#print axioms legal_sequence_representable

end LeanVMBMinCore.AcceptedSequence

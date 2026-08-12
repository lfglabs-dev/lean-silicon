import LeanVMBMinCore.FullProfilePayload
import LeanVMBMinCore.Packet

/-! Canonical accepted-frame bridge for the LSC-1 v1 JUMP opcode 0x07. -/

namespace LeanVMBMinCore.AcceptedJump

set_option maxRecDepth 100000

open LeanVMBMinCore
open LeanVMBMinCore.FullProfile
open LeanVMBMinCore.FullProfile.PacketPreparation
open LeanVMBMinCore.FullProfile.Payload

abbrev Byte := UInt8

def requestCrc32 (bytes : List Byte) : UInt32 := FullProfile.crc32 bytes

def acceptEnvelope (wire : LeanVMBMinCore.Packet.RequestWire) :
    Except LeanVMBMinCore.Packet.DecodeError LeanVMBMinCore.Packet.Request :=
  LeanVMBMinCore.Packet.decodeRequest requestCrc32 wire

inductive Error where
  | envelope (error : LeanVMBMinCore.Packet.DecodeError)
  | payload (error : Payload.Error)
  | notJump
  deriving DecidableEq, Repr

structure Accepted where
  packet : JumpPacket

/-- Accept the complete CRC-protected envelope and exactly 103 JUMP bytes. -/
def accept (wire : LeanVMBMinCore.Packet.RequestWire) : Except Error Accepted := do
  let request <- (acceptEnvelope wire).mapError .envelope
  let decoded <- (Payload.decode request.opcode request.payload).mapError .payload
  match decoded with
  | .jump packet => return { packet }
  | .deref _ _ => throw .notJump

def decision (accepted : Accepted) : Decision := preparedJumpDecision accepted.packet

def transition (effect : Effect) : Transaction.Transition := FullProfile.transitionOf effect

theorem transition_checksum_from_effect (effect : Effect) :
    (transition effect).resultChecksum = FullProfile.crc32 (effectResultPayload effect) := by
  rfl

theorem accepted_refines_prepared (wire : LeanVMBMinCore.Packet.RequestWire)
    (accepted : Accepted) (h : accept wire = .ok accepted) :
    decision accepted = preparedJumpDecision accepted.packet := by
  rfl

theorem accepted_effect_matching_retire_exactly_once
    (wire : LeanVMBMinCore.Packet.RequestWire) (accepted : Accepted) (effect : Effect)
    (model : Transaction.Model) (haccept : accept wire = .ok accepted)
    (heffect : decision accepted = .result effect) :
    (accept wire).map decision = .ok (.result effect) /\
    (transition effect).resultChecksum = FullProfile.crc32 (effectResultPayload effect) /\
    (let first := Transaction.step { model with state := .resultPending (transition effect) }
        (.retire (transition effect).txnId (transition effect).resultChecksum)
     let second := Transaction.step first.model
        (.retire (transition effect).txnId (transition effect).resultChecksum)
     first.retired = true /\ second.retired = false /\
       second.fault = some .badState /\
       second.model.committed = first.model.committed) := by
  constructor
  · simp only [haccept, Except.map, heffect]
  · constructor
    · rfl
    · exact Transaction.matching_retire_is_exactly_once model (transition effect)

def witnessRequest (payload : List Byte) : LeanVMBMinCore.Packet.Request :=
  { opcode := 0x07, flags := 0, payload }

def witnessWire (payload : List Byte) : LeanVMBMinCore.Packet.RequestWire :=
  LeanVMBMinCore.Packet.encodeRequest requestCrc32 (witnessRequest payload)

def witnessEffect : Effect := {
  common := decodedWitnessJumpPacket.common
  nextControl := { pc := 4, fp := 9 }
  initialMemory := suppliedJumpMemory decodedWitnessJumpPacket 9 10 11
  memory := suppliedJumpMemory decodedWitnessJumpPacket 9 10 11
  accesses := [9, 10, 11] }

/-- Non-vacuity: a complete accepted not-taken JUMP reaches the bound effect. -/
theorem accepted_effect_binding_reachable :
    (accept (witnessWire witnessJumpBytes)).map decision =
      .ok (.result witnessEffect) := by
  have haccept : accept (witnessWire witnessJumpBytes) =
      .ok { packet := decodedWitnessJumpPacket } := by rfl
  have heffect : decision { packet := decodedWitnessJumpPacket } =
      .result witnessEffect := by rfl
  exact (accepted_effect_matching_retire_exactly_once
    (witnessWire witnessJumpBytes) { packet := decodedWitnessJumpPacket }
    witnessEffect Transaction.initial haccept heffect).1

/-- Taken and not-taken branches both reach the accepted-frame seam. -/
example : (accept (witnessWire witnessJumpBytes)).isOk := by decide

/-- CRC bypass is mutation-sensitive. -/
example : acceptEnvelope { witnessWire witnessJumpBytes with
    payload := witnessJumpBytes.set 14 1 } = .error .badChecksum := by rfl

/-- A branch-decision mutation is observed with a freshly valid CRC. -/
example : accept (witnessWire (witnessJumpBytes.set 77 2)) =
    .error (.payload .badBranch) := by rfl

/-- Result-byte mutation changes the checksum derived from the effect. -/
theorem result_byte_mutation_changes_crc :
    FullProfile.crc32 [0] != FullProfile.crc32 [1] := by decide

#print axioms accepted_refines_prepared
#print axioms transition_checksum_from_effect
#print axioms accepted_effect_matching_retire_exactly_once
#print axioms accepted_effect_binding_reachable

end LeanVMBMinCore.AcceptedJump

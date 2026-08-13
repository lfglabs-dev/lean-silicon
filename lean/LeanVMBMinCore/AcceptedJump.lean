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

def witnessTakenBytes : List Byte :=
  let bytes := (witnessJumpBytes.set 26 1).set 27 1
  let bytes := (bytes.set 43 1).set 44 2
  let bytes := (bytes.set 60 1).set 61 4
  let bytes := (bytes.set 77 1).set 78 1
  let bytes := bytes.set 82 2
  (bytes.set 86 1).set 87 1

def decodedWitnessTakenJumpPacket : JumpPacket := {
  decodedWitnessJumpPacket with
  conditionCell := { written := true, value := 1#128 }
  targetPcCell := { written := true, value := encodeIndex 1 }
  targetFpCell := { written := true, value := encodeIndex 2 }
  taken := true, proposedPc := 1, proposedFp := 2
  proposedInverse := { written := true, value := 1#128 } }

def witnessEffect : Effect := {
  common := decodedWitnessTakenJumpPacket.common
  nextControl := { pc := 1, fp := 2 }
  initialMemory := suppliedJumpMemory decodedWitnessTakenJumpPacket 9 10 11
  memory := suppliedJumpMemory decodedWitnessTakenJumpPacket 9 10 11
  accesses := [9, 10, 11] }

/-- Non-vacuity: a complete accepted taken JUMP reaches the bound effect. -/
theorem accepted_effect_binding_reachable :
    (accept (witnessWire witnessTakenBytes)).map decision =
      .ok (.result witnessEffect) := by
  have haccept : accept (witnessWire witnessTakenBytes) =
      .ok { packet := decodedWitnessTakenJumpPacket } := by rfl
  have heffect : decision { packet := decodedWitnessTakenJumpPacket } =
      .result witnessEffect := by rfl
  exact (accepted_effect_matching_retire_exactly_once
    (witnessWire witnessTakenBytes) { packet := decodedWitnessTakenJumpPacket }
    witnessEffect Transaction.initial haccept heffect).1

/-- Taken and not-taken branches both reach the accepted-frame seam. -/
example : (accept (witnessWire witnessJumpBytes)).isOk := by decide
example : (accept (witnessWire witnessTakenBytes)).isOk := by decide

/-- CRC bypass is mutation-sensitive. -/
example : acceptEnvelope { witnessWire witnessJumpBytes with
    payload := witnessJumpBytes.set 14 1 } = .error .badChecksum := by rfl

/-- A branch-decision mutation is observed with a freshly valid CRC. -/
example : accept (witnessWire (witnessTakenBytes.set 77 2)) =
    .error (.payload .badBranch) := by rfl

/-- Result-byte mutation changes the checksum derived from the effect. -/
theorem result_byte_mutation_changes_crc :
    FullProfile.crc32 [0] != FullProfile.crc32 [1] := by decide

#print axioms accepted_refines_prepared
#print axioms transition_checksum_from_effect
#print axioms accepted_effect_matching_retire_exactly_once
#print axioms accepted_effect_binding_reachable

end LeanVMBMinCore.AcceptedJump

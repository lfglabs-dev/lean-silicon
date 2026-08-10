import LeanVMBMinCore.FullProfilePayload
import LeanVMBMinCore.Packet

/-! Canonical accepted-frame bridge for LSC-1 v1 DEREF opcodes 0x04--0x06. -/

namespace LeanVMBMinCore.AcceptedDeref

set_option maxRecDepth 100000

open LeanVMBMinCore
open LeanVMBMinCore.FullProfile
open LeanVMBMinCore.FullProfile.PacketPreparation
open LeanVMBMinCore.FullProfile.Payload

abbrev Byte := UInt8

def requestCrc32 (bytes : List Byte) : UInt32 := FullProfile.crc32 bytes

/-- The complete v1 envelope accepted before opcode-specific payload decoding. -/
def acceptEnvelope (wire : LeanVMBMinCore.Packet.RequestWire) :
    Except LeanVMBMinCore.Packet.DecodeError LeanVMBMinCore.Packet.Request :=
  LeanVMBMinCore.Packet.decodeRequest requestCrc32 wire

inductive Error where
  | envelope (error : LeanVMBMinCore.Packet.DecodeError)
  | payload (error : Payload.Error)
  | notDeref
  deriving DecidableEq, Repr

structure Accepted where
  mode : ControlPrimitives.DerefMode
  packet : DerefPacket

/-- Accept a canonical CRC-protected v1 frame and decode its exact 81-byte payload. -/
def accept (wire : LeanVMBMinCore.Packet.RequestWire) : Except Error Accepted := do
  let request <- (acceptEnvelope wire).mapError .envelope
  let decoded <- (Payload.decode request.opcode request.payload).mapError .payload
  match decoded with
  | .deref mode packet => return { mode, packet }
  | .jump _ => throw .notDeref

/-- Preparation is exactly the established DEREF decision, with no alternate semantics. -/
def decision (accepted : Accepted) : Decision :=
  preparedDerefDecision accepted.mode accepted.packet

/-- A successful effect owns its result bytes and therefore its RETIRE checksum. -/
def transition (effect : Effect) : Transaction.Transition := FullProfile.transitionOf effect

theorem transition_checksum_from_effect (effect : Effect) :
    (transition effect).resultChecksum = FullProfile.crc32 (effectResultPayload effect) := by
  rfl

theorem accepted_refines_prepared (wire : LeanVMBMinCore.Packet.RequestWire) (accepted : Accepted)
    (h : accept wire = .ok accepted) :
    decision accepted = preparedDerefDecision accepted.mode accepted.packet := by
  rfl

theorem accepted_cell_refines_prepared (wire : LeanVMBMinCore.Packet.RequestWire) (packet : DerefPacket)
    (h : accept wire = .ok { mode := .cell, packet }) :
    decision { mode := .cell, packet } = preparedDerefDecision .cell packet := by rfl

theorem accepted_pc_refines_prepared (wire : LeanVMBMinCore.Packet.RequestWire) (packet : DerefPacket)
    (h : accept wire = .ok { mode := .pc, packet }) :
    decision { mode := .pc, packet } = preparedDerefDecision .pc packet := by rfl

theorem accepted_fp_refines_prepared (wire : LeanVMBMinCore.Packet.RequestWire) (packet : DerefPacket)
    (h : accept wire = .ok { mode := .fp, packet }) :
    decision { mode := .fp, packet } = preparedDerefDecision .fp packet := by rfl

/-- An accepted successful effect retires with its own payload CRC exactly once. -/
theorem accepted_effect_matching_retire_exactly_once
    (wire : LeanVMBMinCore.Packet.RequestWire) (accepted : Accepted) (effect : Effect)
    (model : Transaction.Model) (_haccept : accept wire = .ok accepted)
    (_heffect : decision accepted = .result effect) :
    (transition effect).resultChecksum = FullProfile.crc32 (effectResultPayload effect) /\
    (let first := Transaction.step { model with state := .resultPending (transition effect) }
        (.retire (transition effect).txnId (transition effect).resultChecksum)
     let second := Transaction.step first.model
        (.retire (transition effect).txnId (transition effect).resultChecksum)
     first.retired = true /\ second.retired = false /\
       second.fault = some .badState /\
       second.model.committed = first.model.committed) := by
  constructor
  · rfl
  · exact Transaction.matching_retire_is_exactly_once model (transition effect)

def witnessRequest (opcode : Byte) (payload : List Byte) : LeanVMBMinCore.Packet.Request :=
  { opcode, flags := 0, payload }

def witnessWire (opcode : Byte) (payload : List Byte) : LeanVMBMinCore.Packet.RequestWire :=
  LeanVMBMinCore.Packet.encodeRequest requestCrc32 (witnessRequest opcode payload)

example : accept (witnessWire 0x04 witnessDerefBytes) =
    .ok { mode := .cell, packet := decodedWitnessDerefPacket } := by rfl

def quadrantBytes (profile targetPresent localPresent : Bool) : List Byte :=
  let bytes := witnessDerefBytes.set 12 (if profile then 1 else 0)
  let bytes := (bytes.set 47 (if targetPresent then 1 else 0)).set 48
    (if targetPresent then 42 else 0)
  (bytes.set 64 (if localPresent then 1 else 0)).set 65
    (if localPresent then 42 else 0)

/-- Both profiles and all four Cell presence quadrants reach accepted frames. -/
example : (accept (witnessWire 0x04 (quadrantBytes false false false))).isOk := by decide
example : (accept (witnessWire 0x04 (quadrantBytes false false true))).isOk := by decide
example : (accept (witnessWire 0x04 (quadrantBytes false true false))).isOk := by decide
example : (accept (witnessWire 0x04 (quadrantBytes false true true))).isOk := by decide
example : (accept (witnessWire 0x04 (quadrantBytes true false false))).isOk := by decide
example : (accept (witnessWire 0x04 (quadrantBytes true false true))).isOk := by decide
example : (accept (witnessWire 0x04 (quadrantBytes true true false))).isOk := by decide
example : (accept (witnessWire 0x04 (quadrantBytes true true true))).isOk := by decide

/-- All three DEREF modes reach the accepted-frame/preparation seam. -/
example : (accept (witnessWire 0x04 witnessDerefBytes)).isOk := by decide
example : (accept (witnessWire 0x05 witnessDerefBytes)).isOk := by decide
example : (accept (witnessWire 0x06 witnessDerefBytes)).isOk := by decide

/-- CRC bypass is mutation-sensitive: changing a covered payload byte is rejected. -/
example : acceptEnvelope { witnessWire 0x04 witnessDerefBytes with
    payload := witnessDerefBytes.set 14 1 } = .error .badChecksum := by rfl

/-- Hidden absent-cell values are rejected even under a freshly valid frame CRC. -/
example : accept (witnessWire 0x04 (witnessDerefBytes.set 48 1)) =
    .error (.payload .badCell) := by rfl

/-- Result-byte mutation changes the checksum derived from the actual effect. -/
theorem result_byte_mutation_changes_crc :
    FullProfile.crc32 [0] != FullProfile.crc32 [1] := by decide

#print axioms accepted_refines_prepared
#print axioms transition_checksum_from_effect
#print axioms accepted_effect_matching_retire_exactly_once

end LeanVMBMinCore.AcceptedDeref

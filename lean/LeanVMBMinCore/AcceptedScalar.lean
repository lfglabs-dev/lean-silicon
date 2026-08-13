import LeanVMBMinCore.FullProfilePayload
import LeanVMBMinCore.Packet

/-! Canonical accepted-frame bridge for LSC-1 v1 SET, XOR, and MUL. -/

namespace LeanVMBMinCore.AcceptedScalar

set_option maxRecDepth 100000

open LeanVMBMinCore
open LeanVMBMinCore.FullProfile
open LeanVMBMinCore.FullProfile.PacketPreparation
open LeanVMBMinCore.FullProfile.Payload

abbrev Byte := UInt8

def requestCrc32 (bytes : List Byte) : UInt32 := FullProfile.crc32 bytes

inductive Operation where | set | xor | mul deriving DecidableEq, Repr

inductive Error where
  | envelope (error : Packet.DecodeError)
  | payload (error : Payload.Error)
  | wrongOperation
  deriving DecidableEq, Repr

structure Accepted where
  operation : Operation
  decoded : Payload.Decoded

def operationOf : Payload.Decoded -> Option Operation
  | .set _ => some .set
  | .binary true _ => some .xor
  | .binary false _ => some .mul
  | _ => none

def accept (wire : Packet.RequestWire) : Except Error Accepted := do
  let request <- (Packet.decodeRequest requestCrc32 wire).mapError .envelope
  let decoded <- (Payload.decode request.opcode request.payload).mapError .payload
  match operationOf decoded with
  | some operation => return { operation, decoded }
  | none => throw .wrongOperation

def decision (accepted : Accepted) : Decision := Payload.decideDecoded accepted.decoded

def transition (effect : Effect) : Transaction.Transition := transitionOf effect

theorem accepted_refines_prepared (wire : Packet.RequestWire) (accepted : Accepted)
    (h : accept wire = .ok accepted) :
    (accept wire).map decision = .ok (decision accepted) := by
  rw [h]
  rfl

theorem accepted_effect_matching_retire_exactly_once
    (wire : Packet.RequestWire) (accepted : Accepted) (effect : Effect)
    (model : Transaction.Model) (haccept : accept wire = .ok accepted)
    (heffect : decision accepted = .result effect) :
    (accept wire).map decision = .ok (.result effect) /\
    (transition effect).resultChecksum = FullProfile.crc32 (effectResultPayload effect) /\
    (let first := Transaction.step { model with state := .resultPending (transition effect) }
        (.retire (transition effect).txnId (transition effect).resultChecksum)
     let second := Transaction.step first.model
        (.retire (transition effect).txnId (transition effect).resultChecksum)
     first.retired = true /\ second.retired = false /\
       second.fault = some .badState /\ second.model.committed = first.model.committed) := by
  constructor
  · simp only [haccept, Except.map, heffect]
  · exact ⟨rfl, Transaction.matching_retire_is_exactly_once model (transition effect)⟩

def request (opcode : Byte) (payload : List Byte) : Packet.Request :=
  { opcode, flags := 0, payload }

def wire (opcode : Byte) (payload : List Byte) : Packet.RequestWire :=
  Packet.encodeRequest requestCrc32 (request opcode payload)

def commonBytes : List Byte := u32le 1 ++ u32le 0 ++ u32le 0 ++ [1, 0]
def setBytes : List Byte := commonBytes ++ u32le 3 ++ wordle 42 ++ cellBytes false 0
def binaryBytes (right : Nat) (withInverse : Bool) : List Byte :=
  commonBytes ++ u32le 1 ++ u32le 2 ++ u32le 3 ++
    cellBytes true 18 ++ cellBytes true right ++ cellBytes false 0 ++
    (if withInverse then cellBytes false 0 else [])

example : setBytes.length = 51 := by decide
example : (binaryBytes 52 false).length = 77 := by decide
example : (binaryBytes 1 true).length = 94 := by decide
example : (accept (wire 0x03 setBytes)).isOk := by decide
example : (accept (wire 0x01 (binaryBytes 52 false))).isOk := by decide
example : (accept (wire 0x02 (binaryBytes 1 true))).isOk := by decide

def witnessCommon : Common := {
  txnId := 1, control := { pc := 0, fp := 0 }, resultChecksum := 0 }

def witnessSetPacket : SetPacket := {
  common := witnessCommon, outputOffset := 3, constant := 42#128
  outputCell := { written := false, value := 0#128 } }

def witnessBinaryPacket (right : Nat) : BinaryPacket := {
  common := witnessCommon, profile := .interpreterCompat
  leftOffset := 1, rightOffset := 2, outputOffset := 3
  leftCell := { written := true, value := 18#128 }
  rightCell := { written := true, value := BitVec.ofNat 128 right }
  outputCell := { written := false, value := 0#128 }
  proposedInverse := { written := false, value := 0#128 } }

def witnessSetEffect : Effect := {
  common := witnessCommon, nextControl := { pc := 1, fp := 0 }
  memory := Memory.writeRaw Memory.empty 3 (42#128), accesses := [3] }

def witnessBinaryEffect (right result : Nat) : Effect := {
  common := witnessCommon, nextControl := { pc := 1, fp := 0 }
  initialMemory := suppliedMemory (witnessBinaryPacket right) 1 2 3
  memory := Memory.writeRaw (suppliedMemory (witnessBinaryPacket right) 1 2 3)
    3 (BitVec.ofNat 128 result)
  accesses := [1, 2, 3] }

/-- Non-vacuity: accepted witness decoders and all three successful decisions are reachable. -/
theorem set_decision_reachable :
    decision { operation := .set, decoded := .set witnessSetPacket } =
      .result witnessSetEffect := by rfl

theorem xor_decision_reachable :
    decision { operation := .xor, decoded := .binary true (witnessBinaryPacket 52) } =
      .result (witnessBinaryEffect 52 38) := by rfl

theorem mul_decision_reachable :
    decision { operation := .mul, decoded := .binary false (witnessBinaryPacket 1) } =
      .result (witnessBinaryEffect 1 18) := by rfl

theorem result_byte_mutation_changes_crc :
    FullProfile.crc32 [0] != FullProfile.crc32 [1] := by decide

#print axioms accepted_refines_prepared
#print axioms accepted_effect_matching_retire_exactly_once
#print axioms set_decision_reachable
#print axioms xor_decision_reachable
#print axioms mul_decision_reachable

end LeanVMBMinCore.AcceptedScalar

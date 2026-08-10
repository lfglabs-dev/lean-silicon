import LeanVMBMinCore.FullProfilePacket

/-!
Byte-exact payload decoding for the v1 raw DEREF/JUMP preparation boundary.

The request wire does not contain the result checksum: the endpoint derives it
from the response payload.  Consequently `decode` takes that transaction-layer
value explicitly and does not pretend it was decoded from host bytes.
-/

namespace LeanVMBMinCore.FullProfile.Payload

set_option maxRecDepth 100000

open LeanVMBMinCore
open LeanVMBMinCore.Memory
open LeanVMBMinCore.FullProfile
open LeanVMBMinCore.FullProfile.PacketPreparation

abbrev Byte := UInt8

inductive Error where
  | badOpcode
  | badLength
  | badProfile
  | badFlags
  | badCell
  | badBranch
  deriving DecidableEq, Repr

inductive Decoded where
  | deref (mode : ControlPrimitives.DerefMode) (packet : DerefPacket)
  | jump (packet : JumpPacket)

def byteAt (bytes : List Byte) (offset : Nat) : Byte :=
  bytes.getD offset 0

def natLE (bytes : List Byte) (offset width : Nat) : Nat :=
  (List.range width).foldl
    (fun value i => value + (byteAt bytes (offset + i)).toNat * 2 ^ (8 * i)) 0

def u32At (bytes : List Byte) (offset : Nat) : UInt32 :=
  UInt32.ofNat (natLE bytes offset 4)

def wordAt (bytes : List Byte) (offset : Nat) : Word :=
  BitVec.ofNat 128 (natLE bytes offset 16)

def cellAt (bytes : List Byte) (offset : Nat) : Except Error Cell :=
  let present := byteAt bytes offset
  let value := wordAt bytes (offset + 1)
  if present == 0 then
    if value == 0#128 then .ok { written := false, value } else .error .badCell
  else if present == 1 then .ok { written := true, value }
  else .error .badCell

def profileAt (bytes : List Byte) : Except Error Profile :=
  match byteAt bytes 12 with
  | 0 => .ok .forwardOnly
  | 1 => .ok .interpreterCompat
  | _ => .error .badProfile

def commonAt (bytes : List Byte) (resultChecksum : Transaction.ResultChecksum) : Common := {
  txnId := u32At bytes 0
  control := { pc := natLE bytes 4 4, fp := natLE bytes 8 4 }
  resultChecksum }

def decodeDeref (mode : ControlPrimitives.DerefMode) (bytes : List Byte)
    (resultChecksum : Transaction.ResultChecksum) : Except Error Decoded := do
  if bytes.length != 81 then throw .badLength
  let profile <- profileAt bytes
  if byteAt bytes 13 != 0 then throw .badFlags
  let pointer <- cellAt bytes 26
  let target <- cellAt bytes 47
  let localCell <- cellAt bytes 64
  return .deref mode {
    common := commonAt bytes resultChecksum, profile
    alpha := natLE bytes 14 4, beta := natLE bytes 18 4, gamma := natLE bytes 22 4
    pointerCell := pointer, base := natLE bytes 43 4
    targetCell := target, localCell }

def decodeJump (bytes : List Byte) (resultChecksum : Transaction.ResultChecksum) :
    Except Error Decoded := do
  if bytes.length != 103 then throw .badLength
  let _ <- profileAt bytes
  if byteAt bytes 13 != 0 then throw .badFlags
  let condition <- cellAt bytes 26
  let targetPc <- cellAt bytes 43
  let targetFp <- cellAt bytes 60
  let inverse <- cellAt bytes 86
  let taken <- match byteAt bytes 77 with
    | 0 => pure false
    | 1 => pure true
    | _ => throw .badBranch
  return .jump {
    common := commonAt bytes resultChecksum
    conditionOffset := natLE bytes 14 4
    targetPcOffset := natLE bytes 18 4
    targetFpOffset := natLE bytes 22 4
    conditionCell := condition, targetPcCell := targetPc, targetFpCell := targetFp
    taken, proposedPc := natLE bytes 78 4, proposedFp := natLE bytes 82 4
    proposedInverse := inverse }

/-- Decode exactly the four v1 raw DEREF/JUMP request payload opcodes. -/
def decode (opcode : Byte) (bytes : List Byte)
    (resultChecksum : Transaction.ResultChecksum) : Except Error Decoded :=
  match opcode with
  | 0x04 => decodeDeref .cell bytes resultChecksum
  | 0x05 => decodeDeref .pc bytes resultChecksum
  | 0x06 => decodeDeref .fp bytes resultChecksum
  | 0x07 => decodeJump bytes resultChecksum
  | _ => .error .badOpcode

def decideDecoded : Decoded -> Decision
  | .deref mode packet => preparedDerefDecision mode packet
  | .jump packet => preparedJumpDecision packet

/-- Successful byte decoding feeds the already-mechanized raw preparation path. -/
theorem decode_refines_preparation (opcode : Byte) (bytes : List Byte)
    (checksum : Transaction.ResultChecksum) (decoded : Decoded)
    (h : decode opcode bytes checksum = .ok decoded) :
    (decode opcode bytes checksum).map decideDecoded = .ok (decideDecoded decoded) := by
  rw [h]
  rfl

def u32le (value : Nat) : List Byte :=
  (List.range 4).map fun i => UInt8.ofNat (value / 2 ^ (8 * i))

def wordle (value : Nat) : List Byte :=
  (List.range 16).map fun i => UInt8.ofNat (value / 2 ^ (8 * i))

def cellBytes (written : Bool) (value : Nat) : List Byte :=
  [if written then 1 else 0] ++ wordle value

/-- A concrete canonical not-taken JUMP payload; this witnesses decoder reachability. -/
def witnessJumpBytes : List Byte :=
  u32le 7 ++ u32le 3 ++ u32le 9 ++ [1, 0] ++
  u32le 0 ++ u32le 1 ++ u32le 2 ++
  cellBytes false 0 ++ cellBytes false 0 ++ cellBytes false 0 ++
  [0] ++ u32le 0 ++ u32le 0 ++ cellBytes false 0

def decodedWitnessJumpPacket : JumpPacket := {
  witnessJumpPacket with
  common := { witnessCommon with txnId := 7, resultChecksum := 0 } }

/-- A concrete canonical DEREF_CELL payload at the protocol's exact offsets. -/
def witnessDerefBytes : List Byte :=
  u32le 7 ++ u32le 3 ++ u32le 9 ++ [1, 0] ++
  u32le 0 ++ u32le 1 ++ u32le 1 ++
  cellBytes true 4 ++ u32le 2 ++ cellBytes false 0 ++ cellBytes true 42

def decodedWitnessDerefPacket : DerefPacket := {
  witnessDerefPacket with
  common := { witnessCommon with txnId := 7, resultChecksum := 0 } }

example : witnessJumpBytes.length = 103 := by decide

example : witnessDerefBytes.length = 81 := by decide

example : decode 0x04 witnessDerefBytes 0 =
    .ok (.deref .cell decodedWitnessDerefPacket) := by
  rfl

example : exists effect,
    decideDecoded (.deref .cell decodedWitnessDerefPacket) = .result effect := by
  refine ⟨{
    common := decodedWitnessDerefPacket.common
    nextControl := { pc := 4, fp := 9 }
    initialMemory := suppliedDerefMemory decodedWitnessDerefPacket 9 3 10
    memory := writeRaw (suppliedDerefMemory decodedWitnessDerefPacket 9 3 10) 3 (0x2a#128)
    accesses := [9, 3, 10] }, by rfl⟩

example : exists packet,
    decode 0x07 witnessJumpBytes 0 = .ok (.jump packet) := by
  refine ⟨decodedWitnessJumpPacket, by rfl⟩

example : exists effect,
    decideDecoded (.jump decodedWitnessJumpPacket) = .result effect := by
  refine ⟨{
    common := decodedWitnessJumpPacket.common
    nextControl := { pc := 4, fp := 9 }
    initialMemory := suppliedJumpMemory decodedWitnessJumpPacket 9 10 11
    memory := suppliedJumpMemory decodedWitnessJumpPacket 9 10 11
    accesses := [9, 10, 11] }, by rfl⟩

/-- A single-byte branch mutation is observed before packet preparation. -/
example : decode 0x07 (witnessJumpBytes.set 77 2) 0 = .error .badBranch := by
  rfl

/-- A hidden value in an absent cell is rejected at the byte boundary. -/
example : decode 0x07 (witnessJumpBytes.set 27 1) 0 = .error .badCell := by
  rfl

/-- Deref and jump payload widths cannot be interchanged. -/
example : decode 0x04 witnessJumpBytes 0 = .error .badLength := by
  rfl

#print axioms decode_refines_preparation

end LeanVMBMinCore.FullProfile.Payload

import LeanVMBMinCore.FullProfile

/-!
Packet-field preparation for the full-profile functional boundary.

This module begins after byte decoding and before instruction execution.  It
checks every effective address before reconciling repeated addresses, matching
the executable endpoint's fault precedence, then constructs the finite
host-owned memory view consumed by `FullProfile.finishBinary`.
-/

namespace LeanVMBMinCore.FullProfile.PacketPreparation

open LeanVMBMinCore
open LeanVMBMinCore.Memory
open LeanVMBMinCore.FullProfile

structure BinaryPacket where
  common : Common
  profile : Profile
  leftOffset : Index
  rightOffset : Index
  outputOffset : Index
  leftCell : Cell
  rightCell : Cell
  outputCell : Cell
  proposedInverse : Cell

def aliasConflict (left right output : Index)
    (leftCell rightCell outputCell : Cell) : Bool :=
  (left == right && leftCell != rightCell) ||
  (left == output && leftCell != outputCell) ||
  (right == output && rightCell != outputCell)

def putCell (memory : Mem) (address : Index) (cell : Cell) : Mem :=
  if cell.written then writeRaw memory address cell.value else memory

def suppliedMemory (packet : BinaryPacket) (left right output : Index) : Mem :=
  putCell (putCell (putCell Memory.empty left packet.leftCell)
    right packet.rightCell) output packet.outputCell

/--
All address arithmetic precedes alias reconciliation.  Thus any overflowing
offset wins even if two earlier supplied operands contradict one another.
-/
def prepareBinary (packet : BinaryPacket) : Except Fault BinaryInput :=
  match CheckedIndex.add packet.common.control.fp packet.leftOffset with
  | none => .error .address
  | some left =>
      match CheckedIndex.add packet.common.control.fp packet.rightOffset with
      | none => .error .address
      | some right =>
          match CheckedIndex.add packet.common.control.fp packet.outputOffset with
          | none => .error .address
          | some output =>
              if aliasConflict left right output packet.leftCell packet.rightCell
                  packet.outputCell then
                .error .aliasInconsistent
              else
                .ok {
                  common := packet.common
                  profile := packet.profile
                  memory := suppliedMemory packet left right output
                  left, right, output
                  proposedInverse := packet.proposedInverse }

def preparedDecision (isXor : Bool) (packet : BinaryPacket) : Decision :=
  match prepareBinary packet with
  | .error fault => .fault fault
  | .ok input => finishBinary isXor input

def binaryInstruction (isXor : Bool) (input : BinaryInput) : Instruction :=
  if isXor then .xor input else .mul input

theorem left_address_overflow_precedes_alias (packet : BinaryPacket)
    (hoverflow : CheckedIndex.add packet.common.control.fp packet.leftOffset = none) :
    prepareBinary packet = .error .address := by
  simp [prepareBinary, hoverflow]

theorem output_address_overflow_precedes_alias (packet : BinaryPacket)
    (left right : Index)
    (hleft : CheckedIndex.add packet.common.control.fp packet.leftOffset = some left)
    (hright : CheckedIndex.add packet.common.control.fp packet.rightOffset = some right)
    (hoverflow : CheckedIndex.add packet.common.control.fp packet.outputOffset = none) :
    prepareBinary packet = .error .address := by
  simp [prepareBinary, hleft, hright, hoverflow]

theorem inconsistent_left_right_alias_is_rejected (packet : BinaryPacket)
    (address output : Index)
    (hleft : CheckedIndex.add packet.common.control.fp packet.leftOffset = some address)
    (hright : CheckedIndex.add packet.common.control.fp packet.rightOffset = some address)
    (houtput : CheckedIndex.add packet.common.control.fp packet.outputOffset = some output)
    (hcells : packet.leftCell ≠ packet.rightCell) :
    prepareBinary packet = .error .aliasInconsistent := by
  simp [prepareBinary, hleft, hright, houtput, aliasConflict, hcells]

theorem any_binary_alias_conflict_is_rejected (packet : BinaryPacket)
    (left right output : Index)
    (hleft : CheckedIndex.add packet.common.control.fp packet.leftOffset = some left)
    (hright : CheckedIndex.add packet.common.control.fp packet.rightOffset = some right)
    (houtput : CheckedIndex.add packet.common.control.fp packet.outputOffset = some output)
    (halias : aliasConflict left right output packet.leftCell packet.rightCell
      packet.outputCell = true) :
    prepareBinary packet = .error .aliasInconsistent := by
  simp [prepareBinary, hleft, hright, houtput, halias]

theorem prepare_binary_success (packet : BinaryPacket) (left right output : Index)
    (hleft : CheckedIndex.add packet.common.control.fp packet.leftOffset = some left)
    (hright : CheckedIndex.add packet.common.control.fp packet.rightOffset = some right)
    (houtput : CheckedIndex.add packet.common.control.fp packet.outputOffset = some output)
    (halias : aliasConflict left right output packet.leftCell packet.rightCell
      packet.outputCell = false) :
    prepareBinary packet = .ok {
      common := packet.common
      profile := packet.profile
      memory := suppliedMemory packet left right output
      left, right, output
      proposedInverse := packet.proposedInverse } := by
  simp [prepareBinary, hleft, hright, houtput, halias]

theorem prepared_decision_refines_binary (isXor : Bool) (packet : BinaryPacket)
    (input : BinaryInput) (hprepare : prepareBinary packet = .ok input) :
    preparedDecision isXor packet = finishBinary isXor input := by
  simp [preparedDecision, hprepare]

theorem prepared_binary_result_stages (isXor : Bool) (packet : BinaryPacket)
    (input : BinaryInput) (effect : Effect) (model : Transaction.Model)
    (hprepare : prepareBinary packet = .ok input)
    (hresult : preparedDecision isXor packet = .result effect)
    (hrepresentable : Representable effect)
    (hidle : model.state = .idle)
    (hrange : Transaction.currentIndicesInRange (transitionOf effect) = true)
    (hmatch : Transaction.stateMatches model (transitionOf effect) = true) :
    stages model (binaryInstruction isXor input)
      (Transaction.step model (.stage (transitionOf effect))) := by
  have hfinish : finishBinary isXor input = .result effect := by
    simpa [preparedDecision, hprepare] using hresult
  have hdecide : decide (binaryInstruction isXor input) = .result effect := by
    cases isXor <;> simpa [binaryInstruction, decide] using hfinish
  exact decided_result_stages model (binaryInstruction isXor input) effect hdecide
    hrepresentable hidle hrange hmatch

def witnessPacket : BinaryPacket := {
  common := witnessCommon
  profile := .interpreterCompat
  leftOffset := 1
  rightOffset := 2
  outputOffset := 3
  leftCell := { written := true, value := 0x12#128 }
  rightCell := { written := true, value := 0x34#128 }
  outputCell := { written := false, value := 0#128 }
  proposedInverse := { written := false, value := 0#128 } }

example : exists input, prepareBinary witnessPacket = .ok input := by
  let input : BinaryInput := {
    common := witnessCommon
    profile := .interpreterCompat
    memory := suppliedMemory witnessPacket 10 11 12
    left := 10, right := 11, output := 12
    proposedInverse := { written := false, value := 0#128 } }
  refine ⟨input, prepare_binary_success witnessPacket 10 11 12 ?_ ?_ ?_ ?_⟩ <;>
    decide

example : exists effect, preparedDecision true witnessPacket = .result effect := by
  refine ⟨{
    common := witnessCommon
    nextControl := { pc := 4, fp := 9 }
    memory := writeRaw (suppliedMemory witnessPacket 10 11 12) 12 (0x26#128) }, ?_⟩
  rfl

#print axioms left_address_overflow_precedes_alias
#print axioms output_address_overflow_precedes_alias
#print axioms inconsistent_left_right_alias_is_rejected
#print axioms any_binary_alias_conflict_is_rejected
#print axioms prepare_binary_success
#print axioms prepared_decision_refines_binary
#print axioms prepared_binary_result_stages

end LeanVMBMinCore.FullProfile.PacketPreparation

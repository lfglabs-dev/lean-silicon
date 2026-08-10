import LeanVMBMinCore.FullProfile

/-!
Packet-field preparation for the full-profile functional boundary.

This module begins after byte decoding and before instruction execution.  It
checks every effective address before reconciling repeated addresses, matching
the executable endpoint's fault precedence, then constructs the finite
host-owned memory view consumed by `FullProfile.finishBinary`.
-/

namespace LeanVMBMinCore.FullProfile.PacketPreparation

set_option maxRecDepth 10000

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

structure SetPacket where
  common : Common
  outputOffset : Index
  constant : Word
  outputCell : Cell

structure DerefPacket where
  common : Common
  profile : Profile
  alpha : Index
  beta : Index
  gamma : Index
  pointerCell : Cell
  base : Index
  targetCell : Cell
  localCell : Cell

structure JumpPacket where
  common : Common
  conditionOffset : Index
  targetPcOffset : Index
  targetFpOffset : Index
  conditionCell : Cell
  targetPcCell : Cell
  targetFpCell : Cell
  taken : Bool
  proposedPc : Index
  proposedFp : Index
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

def suppliedDerefMemory (packet : DerefPacket)
    (pointer target localAddress : Index) : Mem :=
  materializeSupplied [(pointer, packet.pointerCell), (target, packet.targetCell),
    (localAddress, packet.localCell)]

def suppliedJumpMemory (packet : JumpPacket)
    (condition targetPc targetFp : Index) : Mem :=
  materializeSupplied [(condition, packet.conditionCell), (targetPc, packet.targetPcCell),
    (targetFp, packet.targetFpCell)]

def canonicalDerefCells (packet : DerefPacket) : Bool :=
  canonicalCell packet.pointerCell && canonicalCell packet.targetCell &&
    canonicalCell packet.localCell

def canonicalJumpCells (packet : JumpPacket) : Bool :=
  canonicalCell packet.conditionCell && canonicalCell packet.targetPcCell &&
    canonicalCell packet.targetFpCell && canonicalCell packet.proposedInverse

def derefPcReturnInRange (packet : DerefPacket) : Bool :=
  packet.common.control.pc + 2 < protocolIndexLimit

def jumpTargetInRange (target : Index) : Bool :=
  target < protocolIndexLimit

/-- Raw DEREF preparation in endpoint fault order. -/
def prepareDeref (packet : DerefPacket) : Except Fault DerefInput :=
  if !canonicalDerefCells packet then .error .badCell
  else match CheckedIndex.add packet.common.control.fp packet.alpha with
    | none => .error .address
    | some pointer => match CheckedIndex.add packet.common.control.fp packet.gamma with
      | none => .error .address
      | some localAddress =>
        if packet.base >= 2 ^ 16 then .error .address
        else if !packet.pointerCell.written ||
            packet.pointerCell.value != encodeIndex packet.base then
          .error (.deref .unresolvedPointer)
        else match CheckedIndex.add packet.base packet.beta with
          | none => .error .address
          | some target =>
            let supplied := [(pointer, packet.pointerCell), (target, packet.targetCell),
              (localAddress, packet.localCell)]
            if !suppliedAliasesAgree supplied then .error .aliasInconsistent
            else match CheckedIndex.add packet.common.control.pc 1 with
              | none => .error .address
              | some nextPc => .ok {
                  common := packet.common, profile := packet.profile
                  memory := materializeSupplied supplied
                  prepared := {
                    control := packet.common.control
                    pointerAddress := pointer
                    base := packet.base
                    target := target
                    localAddress := localAddress
                    nextPc := nextPc } }

def preparedDerefDecision (mode : ControlPrimitives.DerefMode)
    (packet : DerefPacket) : Decision :=
  match prepareDeref packet with
  | .error fault => .fault fault
  | .ok input =>
      if mode == .pc && !derefPcReturnInRange packet then
        .fault .address
      else decide (.deref mode input)

/-- Raw JUMP preparation in endpoint fault order. -/
def prepareJump (packet : JumpPacket) : Except Fault JumpInput :=
  if !canonicalJumpCells packet then .error .badCell
  else match CheckedIndex.add packet.common.control.fp packet.conditionOffset with
    | none => .error .address
    | some condition => match CheckedIndex.add packet.common.control.fp packet.targetPcOffset with
      | none => .error .address
      | some targetPc => match CheckedIndex.add packet.common.control.fp packet.targetFpOffset with
        | none => .error .address
        | some targetFp =>
          let supplied := [(condition, packet.conditionCell), (targetPc, packet.targetPcCell),
            (targetFp, packet.targetFpCell)]
          if !suppliedAliasesAgree supplied then .error .aliasInconsistent
          else
            let memory := materializeSupplied supplied
            let actualTaken := (memory condition).value != 0#128
            if actualTaken != packet.taken then .error (.jump .invalidBranch)
            else if actualTaken then
              if !ControlPrimitives.acceptsInverse (memory condition).value
                  packet.proposedInverse.value then .error (.jump .invalidInverse)
              else if !jumpTargetInRange packet.proposedPc then .error .address
              else if encodeIndex packet.proposedPc != (memory targetPc).value then
                .error (.jump .unresolvedPointer)
              else if !jumpTargetInRange packet.proposedFp then .error .address
              else if encodeIndex packet.proposedFp != (memory targetFp).value then
                .error (.jump .unresolvedPointer)
              else .ok {
                common := packet.common, memory
                condition := (memory condition).value
                targetPcWord := (memory targetPc).value
                targetFpWord := (memory targetFp).value
                inverseWitness := packet.proposedInverse.value
                resolvedTargets := some (packet.proposedPc, packet.proposedFp)
                accesses := fun i => [condition, targetPc, targetFp].get i }
            else if packet.proposedInverse.value != 0#128 then
              .error (.jump .invalidInverse)
            else if packet.proposedPc != 0 || packet.proposedFp != 0 then
              .error (.jump .invalidBranch)
            else .ok {
              common := packet.common, memory
              condition := (memory condition).value
              targetPcWord := (memory targetPc).value
              targetFpWord := (memory targetFp).value
              inverseWitness := packet.proposedInverse.value
              resolvedTargets := none
              accesses := fun i => [condition, targetPc, targetFp].get i }

def preparedJumpDecision (packet : JumpPacket) : Decision :=
  match prepareJump packet with
  | .error fault => .fault fault
  | .ok input => decide (.jump input)

theorem prepared_deref_refines_decide (mode : ControlPrimitives.DerefMode)
    (packet : DerefPacket) (input : DerefInput)
    (h : prepareDeref packet = .ok input)
    (hreturn : ¬(mode = .pc ∧ derefPcReturnInRange packet = false)) :
    preparedDerefDecision mode packet = decide (.deref mode input) := by
  simp [preparedDerefDecision, h, hreturn]

theorem prepared_jump_refines_decide (packet : JumpPacket) (input : JumpInput)
    (h : prepareJump packet = .ok input) :
    preparedJumpDecision packet = decide (.jump input) := by
  simp [preparedJumpDecision, h]

def prepareSet (packet : SetPacket) : Except Fault Instruction :=
  match CheckedIndex.add packet.common.control.fp packet.outputOffset with
  | none => .error .address
  | some output =>
      .ok (.set packet.common (putCell Memory.empty output packet.outputCell)
        output packet.constant)

def preparedSetDecision (packet : SetPacket) : Decision :=
  match prepareSet packet with
  | .error fault => .fault fault
  | .ok instruction => decide instruction

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

theorem set_address_overflow_is_rejected (packet : SetPacket)
    (hoverflow : CheckedIndex.add packet.common.control.fp packet.outputOffset = none) :
    prepareSet packet = .error .address := by
  simp [prepareSet, hoverflow]

theorem prepare_set_success (packet : SetPacket) (output : Index)
    (houtput : CheckedIndex.add packet.common.control.fp packet.outputOffset = some output) :
    prepareSet packet = .ok
      (.set packet.common (putCell Memory.empty output packet.outputCell)
        output packet.constant) := by
  simp [prepareSet, houtput]

theorem prepared_set_refines_decide (packet : SetPacket) (instruction : Instruction)
    (hprepare : prepareSet packet = .ok instruction) :
    preparedSetDecision packet = decide instruction := by
  simp [preparedSetDecision, hprepare]

theorem prepared_set_result_stages (packet : SetPacket) (instruction : Instruction)
    (effect : Effect) (model : Transaction.Model)
    (hprepare : prepareSet packet = .ok instruction)
    (hresult : preparedSetDecision packet = .result effect)
    (hrepresentable : Representable effect)
    (hidle : model.state = .idle)
    (hrange : Transaction.currentIndicesInRange (transitionOf effect) = true)
    (hmatch : Transaction.stateMatches model (transitionOf effect) = true) :
    stages model instruction
      (Transaction.step model (.stage (transitionOf effect))) := by
  have hdecide : decide instruction = .result effect := by
    simpa [preparedSetDecision, hprepare] using hresult
  exact decided_result_stages model instruction effect hdecide hrepresentable
    hidle hrange hmatch

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

def witnessSetPacket : SetPacket := {
  common := witnessCommon
  outputOffset := 3
  constant := 0x2a#128
  outputCell := { written := false, value := 0#128 } }

example : prepareSet witnessSetPacket =
    .ok (.set witnessCommon (putCell Memory.empty 12 witnessSetPacket.outputCell)
      12 (0x2a#128)) := by
  exact prepare_set_success witnessSetPacket 12 (by decide)

example : exists effect, preparedSetDecision witnessSetPacket = .result effect := by
  refine ⟨{
    common := witnessCommon
    nextControl := { pc := 4, fp := 9 }
    memory := writeRaw Memory.empty 12 (0x2a#128)
    accesses := [12] }, ?_⟩
  rfl

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
    initialMemory := suppliedMemory witnessPacket 10 11 12
    memory := writeRaw (suppliedMemory witnessPacket 10 11 12) 12 (0x26#128)
    accesses := [10, 11, 12] }, ?_⟩
  rfl

def witnessDerefPacket : DerefPacket := {
  common := witnessCommon, profile := .interpreterCompat
  alpha := 0, beta := 1, gamma := 1
  pointerCell := { written := true, value := encodeIndex 2 }
  base := 2
  targetCell := { written := false, value := 0#128 }
  localCell := { written := true, value := 0x2a#128 } }

def witnessJumpPacket : JumpPacket := {
  common := witnessCommon
  conditionOffset := 0, targetPcOffset := 1, targetFpOffset := 2
  conditionCell := { written := false, value := 0#128 }
  targetPcCell := { written := false, value := 0#128 }
  targetFpCell := { written := false, value := 0#128 }
  taken := false, proposedPc := 0, proposedFp := 0
  proposedInverse := { written := false, value := 0#128 } }

def witnessTakenJumpPacket : JumpPacket := {
  witnessJumpPacket with
  conditionCell := { written := true, value := 1#128 }
  targetPcCell := { written := true, value := encodeIndex 5 }
  targetFpCell := { written := true, value := encodeIndex 6 }
  taken := true, proposedPc := 5, proposedFp := 6
  proposedInverse := { written := true, value := 1#128 } }

example : (prepareDeref witnessDerefPacket).isOk := by decide

example : exists effect,
    preparedDerefDecision .cell witnessDerefPacket = .result effect := by
  refine ⟨{
    common := witnessCommon, nextControl := { pc := 4, fp := 9 }
    initialMemory := suppliedDerefMemory witnessDerefPacket 9 3 10
    memory := writeRaw (suppliedDerefMemory witnessDerefPacket 9 3 10) 3 (0x2a#128)
    accesses := [9, 3, 10] }, ?_⟩
  rfl

example : (prepareJump witnessJumpPacket).isOk := by decide

example : exists effect, preparedJumpDecision witnessJumpPacket = .result effect := by
  refine ⟨{
    common := witnessCommon, nextControl := { pc := 4, fp := 9 }
    initialMemory := suppliedJumpMemory witnessJumpPacket 9 10 11
    memory := suppliedJumpMemory witnessJumpPacket 9 10 11
    accesses := [9, 10, 11] }, ?_⟩
  rfl

example : exists effect,
    preparedJumpDecision witnessTakenJumpPacket = .result effect := by
  refine ⟨{
    common := witnessCommon, nextControl := { pc := 5, fp := 6 }
    initialMemory := suppliedJumpMemory witnessTakenJumpPacket 9 10 11
    memory := suppliedJumpMemory witnessTakenJumpPacket 9 10 11
    accesses := [9, 10, 11] }, ?_⟩
  rfl

/-- BAD_CELL is established while decoding, before address arithmetic. -/
example : prepareDeref { witnessDerefPacket with
    alpha := CheckedIndex.max, pointerCell := { written := false, value := 1#128 } } =
    .error .badCell := by rfl

example : prepareDeref { witnessDerefPacket with alpha := CheckedIndex.max } =
    .error .address := by rfl

example : prepareJump { witnessJumpPacket with
    conditionCell := { written := false, value := 1#128 } } =
    .error .badCell := by rfl

/-- The bounded base proposal is rejected before pointer or target inspection. -/
example : prepareDeref { witnessDerefPacket with
    base := 2 ^ 16, pointerCell := { written := true, value := 0#128 }
    beta := CheckedIndex.max } = .error .address := by rfl

/-- Pointer re-encoding failure precedes overflowing `base + beta`. -/
example : prepareDeref { witnessDerefPacket with
    pointerCell := { written := true, value := 0#128 }
    beta := CheckedIndex.max } = .error (.deref .unresolvedPointer) := by rfl

example : prepareDeref { witnessDerefPacket with
    base := 9, beta := 0
    pointerCell := { written := true, value := encodeIndex 9 }
    targetCell := { written := true, value := 0x2a#128 } } =
    .error .aliasInconsistent := by rfl

/-- DEREF_PC cannot encode the first index outside the protocol domain. -/
example : preparedDerefDecision .pc { witnessDerefPacket with
    common := { witnessCommon with control := { pc := protocolIndexLimit - 2, fp := 9 } } } =
    .fault .address := by rfl

/-- The immediately preceding DEREF_PC return index remains admissible. -/
example : derefPcReturnInRange { witnessDerefPacket with
    common := { witnessCommon with control := { pc := protocolIndexLimit - 3, fp := 9 } } } :=
  by decide

example : !derefPcReturnInRange { witnessDerefPacket with
    common := { witnessCommon with control := { pc := protocolIndexLimit - 2, fp := 9 } } } :=
  by decide

/-- The return-index bound is specific to DEREF_PC; DEREF_FP keeps this boundary packet. -/
example : exists effect, preparedDerefDecision .fp { witnessDerefPacket with
    common := { witnessCommon with control := { pc := protocolIndexLimit - 2, fp := 9 } } } =
    .result effect := by
  refine ⟨{
    common := { witnessCommon with control := { pc := protocolIndexLimit - 2, fp := 9 } }
    nextControl := { pc := protocolIndexLimit - 1, fp := 9 }
    initialMemory := suppliedDerefMemory witnessDerefPacket 9 3 10
    memory := writeRaw (suppliedDerefMemory witnessDerefPacket 9 3 10) 3 (encodeIndex 9)
    accesses := [9, 3, 10] }, ?_⟩
  rfl

/-- Earlier supplied-cell alias faults still precede the DEREF_PC return bound. -/
example : preparedDerefDecision .pc { witnessDerefPacket with
    common := { witnessCommon with control := { pc := protocolIndexLimit - 2, fp := 9 } }
    base := 9, beta := 0
    pointerCell := { written := true, value := encodeIndex 9 }
    targetCell := { written := true, value := 0x2a#128 } } =
    .fault .aliasInconsistent := by rfl

/-- Checked JUMP address arithmetic precedes supplied-cell alias reconciliation. -/
example : prepareJump { witnessJumpPacket with
    conditionOffset := CheckedIndex.max } = .error .address := by rfl

/-- Checked JUMP address arithmetic precedes supplied-cell alias reconciliation. -/
example : prepareJump { witnessJumpPacket with
    conditionOffset := CheckedIndex.max, targetPcOffset := CheckedIndex.max
    conditionCell := { written := true, value := 1#128 }
    targetPcCell := { written := true, value := 2#128 } } = .error .address := by rfl

/-- Alias consistency precedes the branch-outcome proposal. -/
example : prepareJump { witnessJumpPacket with
    targetPcOffset := 0, taken := true
    conditionCell := { written := false, value := 0#128 }
    targetPcCell := { written := true, value := 1#128 } } =
    .error .aliasInconsistent := by rfl

/-- The declared outcome is rejected before the inverse proposal is executed. -/
example : preparedJumpDecision { witnessJumpPacket with
    taken := true, proposedInverse := { written := true, value := 2#128 } } =
    .fault (.jump .invalidBranch) := by rfl


example : preparedJumpDecision { witnessTakenJumpPacket with taken := false } =
    .fault (.jump .invalidBranch) := by rfl

example : prepareJump { witnessJumpPacket with proposedPc := 1 } =
    .error (.jump .invalidBranch) := by rfl

/-- The first taken JUMP destination is bounded by the protocol index domain. -/
example : prepareJump { witnessTakenJumpPacket with
    proposedPc := protocolIndexLimit
    targetPcCell := { written := true, value := encodeIndex protocolIndexLimit } } =
    .error .address := by rfl

/-- The second taken JUMP destination is independently bounded. -/
example : prepareJump { witnessTakenJumpPacket with
    proposedFp := protocolIndexLimit
    targetFpCell := { written := true, value := encodeIndex protocolIndexLimit } } =
    .error .address := by rfl

/-- The shared taken-target predicate admits exactly the last protocol index. -/
example : jumpTargetInRange (protocolIndexLimit - 1) := by decide

example : !jumpTargetInRange protocolIndexLimit := by decide

/-- Inverse validation precedes both taken-target range checks. -/
example : prepareJump { witnessTakenJumpPacket with
    proposedPc := protocolIndexLimit
    targetPcCell := { written := true, value := encodeIndex protocolIndexLimit }
    proposedInverse := { written := true, value := 2#128 } } =
    .error (.jump .invalidInverse) := by rfl

/-- PC re-encoding precedes the FP protocol-bound check. -/
example : prepareJump { witnessTakenJumpPacket with
    targetPcCell := { written := true, value := encodeIndex 7 }
    proposedFp := protocolIndexLimit
    targetFpCell := { written := true, value := encodeIndex protocolIndexLimit } } =
    .error (.jump .unresolvedPointer) := by rfl

/-- Non-taken inverse validation precedes the pinned-zero destination proposal. -/
example : prepareJump { witnessJumpPacket with
    proposedPc := 1
    proposedInverse := { written := true, value := 2#128 } } =
    .error (.jump .invalidInverse) := by rfl

#print axioms left_address_overflow_precedes_alias
#print axioms set_address_overflow_is_rejected
#print axioms prepare_set_success
#print axioms prepared_set_refines_decide
#print axioms prepared_set_result_stages
#print axioms output_address_overflow_precedes_alias
#print axioms inconsistent_left_right_alias_is_rejected
#print axioms any_binary_alias_conflict_is_rejected
#print axioms prepare_binary_success
#print axioms prepared_decision_refines_binary
#print axioms prepared_binary_result_stages
#print axioms prepared_deref_refines_decide
#print axioms prepared_jump_refines_decide

end LeanVMBMinCore.FullProfile.PacketPreparation

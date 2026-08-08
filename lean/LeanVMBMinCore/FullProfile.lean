import LeanVMBMinCore.ControlPrimitives
import LeanVMBMinCore.Transaction

/-!
Canonical functional boundary for one full-profile LSC-1 transaction.

The host owns memory and fetch.  Consequently an instruction request contains
the finite memory view and checked proposals needed by the scalar operation.
The endpoint recomputes the effect below; it does not trust a proposed result.
BLAKE3 is deliberately represented only by a typed service request/response.
There is no digest function or cryptographic axiom in this model.
-/

namespace LeanVMBMinCore.FullProfile

set_option maxRecDepth 10000

open LeanVMBMinCore
open LeanVMBMinCore.Memory
open LeanVMBMinCore.ControlPrimitives

abbrev Word := GHASH128.Word
abbrev Index := CheckedIndex.Index

/-- Canonical polynomial-basis encoding of a host-proposed pointer index. -/
def encodeIndex : Index -> Word
  | 0 => 1#128
  | n + 1 => GHASH128.xtime (encodeIndex n)

structure Common where
  txnId : Transaction.TxnId
  control : Control
  resultChecksum : Transaction.ResultChecksum
  deriving DecidableEq, Repr

structure BinaryInput where
  common : Common
  memory : Mem
  left : Index
  right : Index
  output : Index

structure DerefInput where
  common : Common
  memory : Mem
  prepared : PreparedDeref

structure JumpInput where
  common : Common
  condition : Word
  targetPcWord : Word
  targetFpWord : Word
  inverseWitness : Word
  resolvedTargets : Option (Index × Index)

structure Blake3Request where
  common : Common
  serviceId : UInt32
  inputWords : List Word
  chainingValue : List Word
  outputAddresses : Index × Index
  metadata : List UInt8
  deriving DecidableEq, Repr

structure Blake3Response where
  txnId : Transaction.TxnId
  serviceId : UInt32
  digest : Word × Word
  deriving DecidableEq, Repr

inductive Instruction where
  | set (common : Common) (memory : Mem) (address : Index) (constant : Word)
  | xor (input : BinaryInput)
  | mul (input : BinaryInput)
  | deref (mode : DerefMode) (input : DerefInput)
  | jump (input : JumpInput)
  | blake3 (request : Blake3Request)

inductive Fault where
  | writeConflict
  | deref (reason : ControlPrimitives.Fault)
  | jump (reason : ControlPrimitives.Fault)
  | badService
  deriving DecidableEq, Repr

structure Effect where
  common : Common
  nextControl : Control
  memory : Mem
  deferred : List (Index × Index) := []

inductive Decision where
  | result (effect : Effect)
  | serviceRequired (request : Blake3Request)
  | fault (reason : Fault)

def advance (common : Common) : Option Control := do
  let pc <- checkedOffset common.control.pc 1
  some { common.control with pc := pc }

def finishWrite (common : Common) (memory : Mem) (address : Index)
    (value : Word) : Decision :=
  match advance common, writeOnce memory address value with
  | some next, some memory' => .result { common, nextControl := next, memory := memory' }
  | _, _ => .fault .writeConflict

/-- Pure endpoint decision for every full-profile instruction kind. -/
def decide : Instruction -> Decision
  | .set common memory address constant => finishWrite common memory address constant
  | .xor input =>
      finishWrite input.common input.memory input.output
        ((input.memory input.left).value ^^^ (input.memory input.right).value)
  | .mul input =>
      finishWrite input.common input.memory input.output
        (GHASH128.mul (input.memory input.left).value (input.memory input.right).value)
  | .deref mode input =>
      match executeDeref encodeIndex mode input.memory input.prepared with
      | .ok control memory => .result {
          common := input.common, nextControl := control, memory := memory }
      | .deferred control left right memory => .result {
          common := input.common, nextControl := control, memory := memory
          deferred := [(left, right)] }
      | .fault reason => .fault (.deref reason)
  | .jump input =>
      match ControlPrimitives.jump encodeIndex
          input.common.control input.condition input.targetPcWord input.targetFpWord
          input.inverseWitness input.resolvedTargets with
      | .ok control => .result {
          common := input.common, nextControl := control, memory := Memory.empty }
      | .fault reason => .fault (.jump reason)
  | .blake3 request => .serviceRequired request

/-- A service response is accepted only by the request that created it. -/
def resumeBlake3 (request : Blake3Request) (response : Blake3Response) : Decision :=
  if response.txnId != request.common.txnId || response.serviceId != request.serviceId then
    .fault .badService
  else
    let memory := writeRaw
      (writeRaw Memory.empty request.outputAddresses.1 response.digest.1)
      request.outputAddresses.2 response.digest.2
    match advance request.common with
    | some control => .result { common := request.common, nextControl := control, memory := memory }
    | none => .fault .writeConflict

def transitionOf (effect : Effect) : Transaction.Transition := {
  txnId := effect.common.txnId
  currentPc := UInt32.ofNat effect.common.control.pc
  currentFp := UInt32.ofNat effect.common.control.fp
  nextPc := UInt32.ofNat effect.nextControl.pc
  nextFp := UInt32.ofNat effect.nextControl.fp
  resultChecksum := effect.common.resultChecksum
}

/-- Non-vacuous bridge: a functional result is exactly what enters retirement staging. -/
def stages (model : Transaction.Model) (instruction : Instruction)
    (outcome : Transaction.Outcome) : Prop :=
  exists effect, decide instruction = .result effect /\
    outcome = Transaction.step model (.stage (transitionOf effect))

theorem decided_result_stages (model : Transaction.Model) (instruction : Instruction)
    (effect : Effect) (h : decide instruction = .result effect) :
    stages model instruction
      (Transaction.step model (.stage (transitionOf effect))) := by
  exact Exists.intro effect ⟨h, rfl⟩

theorem staged_result_matching_retire_commits (model : Transaction.Model)
    (instruction : Instruction) (effect : Effect)
    (hdecide : decide instruction = .result effect)
    (hidle : model.state = .idle)
    (hrange : Transaction.currentIndicesInRange (transitionOf effect) = true)
    (hmatch : Transaction.stateMatches model (transitionOf effect) = true) :
    let staged := Transaction.step model (.stage (transitionOf effect))
    let retired := Transaction.step staged.model
      (.retire effect.common.txnId effect.common.resultChecksum)
    stages model instruction staged /\
      retired.model.committed.pc = UInt32.ofNat effect.nextControl.pc /\
      retired.model.committed.fp = UInt32.ofNat effect.nextControl.fp /\
      retired.retired = true := by
  have hstage := Transaction.stage_is_atomic model (transitionOf effect)
    hidle hrange hmatch
  dsimp
  constructor
  · exact decided_result_stages model instruction effect hdecide
  · rw [hstage]
    simp [Transaction.step, transitionOf]

theorem staged_result_abort_never_commits (model : Transaction.Model)
    (instruction : Instruction) (effect : Effect)
    (hdecide : decide instruction = .result effect) :
    stages model instruction (Transaction.step model (.stage (transitionOf effect))) /\
      (Transaction.step
        (Transaction.step model (.stage (transitionOf effect))).model .abort).model.committed =
        (Transaction.step model (.stage (transitionOf effect))).model.committed := by
  constructor
  · exact decided_result_stages model instruction effect hdecide
  · exact Transaction.abort_preserves_committed _

theorem blake3_never_decides_digest (request : Blake3Request) :
    decide (.blake3 request) = .serviceRequired request := by rfl

theorem blake3_rejects_wrong_transaction (request : Blake3Request)
    (response : Blake3Response) (h : response.txnId != request.common.txnId) :
    resumeBlake3 request response = .fault .badService := by
  simp [resumeBlake3, h]

theorem blake3_rejects_wrong_service (request : Blake3Request)
    (response : Blake3Response) (h : response.serviceId != request.serviceId) :
    resumeBlake3 request response = .fault .badService := by
  simp [resumeBlake3, h]

theorem xor_uses_supplied_operands (input : BinaryInput) :
    decide (.xor input) = finishWrite input.common input.memory input.output
      ((input.memory input.left).value ^^^ (input.memory input.right).value) := by
  rfl

theorem mul_uses_canonical_ghash (input : BinaryInput) :
    decide (.mul input) = finishWrite input.common input.memory input.output
      (GHASH128.mul (input.memory input.left).value (input.memory input.right).value) := by
  rfl

theorem deref_uses_canonical_control (mode : DerefMode) (input : DerefInput) :
    decide (.deref mode input) =
      match executeDeref encodeIndex mode input.memory input.prepared with
      | .ok control memory => .result {
          common := input.common, nextControl := control, memory := memory }
      | .deferred control left right memory => .result {
          common := input.common, nextControl := control, memory := memory
          deferred := [(left, right)] }
      | .fault reason => .fault (.deref reason) := by
  rfl

theorem jump_uses_canonical_control (input : JumpInput) :
    decide (.jump input) =
      match ControlPrimitives.jump encodeIndex input.common.control input.condition
          input.targetPcWord input.targetFpWord input.inverseWitness input.resolvedTargets with
      | .ok control => .result {
          common := input.common, nextControl := control, memory := Memory.empty }
      | .fault reason => .fault (.jump reason) := by
  rfl

/-! Concrete reachability witnesses keep the relation observably non-empty. -/

def witnessCommon : Common := {
  txnId := 7, control := { pc := 3, fp := 9 }, resultChecksum := 0x1234 }

def witnessSetEffect : Effect where
  common := witnessCommon
  nextControl := { pc := 4, fp := 9 }
  memory := writeRaw Memory.empty 12 (0x2a#128)

example : exists effect, decide (.set witnessCommon Memory.empty 12 (0x2a#128)) = .result effect := by
  refine ⟨witnessSetEffect, ?_⟩
  rfl

example : exists request, decide (.blake3 request) = .serviceRequired request := by
  let request : Blake3Request := {
    common := witnessCommon, serviceId := 11, inputWords := [], chainingValue := [],
    outputAddresses := (20, 21), metadata := [] }
  exact ⟨request, rfl⟩

def witnessBinary : BinaryInput := {
  common := witnessCommon, memory := Memory.empty, left := 1, right := 2, output := 3 }

def witnessZeroEffect : Effect where
  common := witnessCommon
  nextControl := { pc := 4, fp := 9 }
  memory := writeRaw Memory.empty 3 (0#128)

example : exists effect, decide (.xor witnessBinary) = .result effect := by
  refine ⟨witnessZeroEffect, ?_⟩
  rfl

example : exists effect, decide (.mul witnessBinary) = .result effect := by
  refine ⟨witnessZeroEffect, ?_⟩
  rfl

def witnessJump : JumpInput := {
  common := witnessCommon, condition := 0#128, targetPcWord := 0#128,
  targetFpWord := 0#128, inverseWitness := 0#128, resolvedTargets := none }

def witnessJumpEffect : Effect where
  common := witnessCommon
  nextControl := { pc := 4, fp := 9 }
  memory := Memory.empty

example : exists effect, decide (.jump witnessJump) = .result effect := by
  refine ⟨witnessJumpEffect, ?_⟩
  rfl

#print axioms decided_result_stages
#print axioms staged_result_matching_retire_commits
#print axioms staged_result_abort_never_commits
#print axioms blake3_never_decides_digest
#print axioms mul_uses_canonical_ghash
#print axioms deref_uses_canonical_control
#print axioms jump_uses_canonical_control

end LeanVMBMinCore.FullProfile

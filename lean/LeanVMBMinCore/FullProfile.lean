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

inductive Profile where
  | forwardOnly
  | interpreterCompat
  deriving DecidableEq, Repr

structure BinaryInput where
  common : Common
  profile : Profile
  memory : Mem
  left : Index
  right : Index
  output : Index
  proposedInverse : Cell

structure DerefInput where
  common : Common
  profile : Profile
  memory : Mem
  prepared : PreparedDeref

structure JumpInput where
  common : Common
  memory : Mem
  condition : Word
  targetPcWord : Word
  targetFpWord : Word
  inverseWitness : Word
  resolvedTargets : Option (Index × Index)

structure Blake3Request where
  common : Common
  serviceId : UInt32
  memory : Mem
  /-- BLAKE3 compression has exactly four message words. -/
  inputWords : Fin 4 -> Word
  /-- BLAKE3 compression has exactly two chaining-value words. -/
  chainingValue : Fin 2 -> Word
  outputAddresses : Index × Index
  /-- Counter, block length, and flags occupy exactly sixteen bytes. -/
  metadata : Fin 16 -> UInt8

/-- Host-owned BLAKE3 inputs before the endpoint assigns a service identifier. -/
structure Blake3Start where
  common : Common
  memory : Mem
  inputWords : Fin 4 -> Word
  chainingValue : Fin 2 -> Word
  outputAddresses : Index × Index
  metadata : Fin 16 -> UInt8

def Blake3Start.assignServiceId (start : Blake3Start)
    (serviceId : UInt32) : Blake3Request := {
  common := start.common
  serviceId
  memory := start.memory
  inputWords := start.inputWords
  chainingValue := start.chainingValue
  outputAddresses := start.outputAddresses
  metadata := start.metadata }

structure Blake3Response where
  txnId : Transaction.TxnId
  serviceId : UInt32
  digest : Word × Word
  deriving DecidableEq, Repr

structure ServicePending where
  request : Blake3Request
  nextControl : Control

inductive Instruction where
  | set (common : Common) (memory : Mem) (address : Index) (constant : Word)
  | xor (input : BinaryInput)
  | mul (input : BinaryInput)
  | deref (mode : DerefMode) (input : DerefInput)
  | jump (input : JumpInput)
  | blake3 (request : Blake3Request)

inductive Fault where
  | address
  | stateMismatch
  | unsupportedInProfile
  | badInverse
  | mulBacksolveZero
  | aliasInconsistent
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
  | serviceRequired (pending : ServicePending)
  | fault (reason : Fault)

def advance (common : Common) : Option Control := do
  let pc <- checkedOffset common.control.pc 1
  some { common.control with pc := pc }

def finishWrite (common : Common) (memory : Mem) (address : Index)
    (value : Word) : Decision :=
  match advance common with
  | none => .fault .address
  | some next =>
      match writeOnce memory address value with
      | some memory' => .result { common, nextControl := next, memory := memory' }
      | none => .fault .writeConflict

def finishBinary (isXor : Bool) (input : BinaryInput) : Decision :=
  let leftAbsent := !(input.memory input.left).written
  let rightAbsent := !(input.memory input.right).written
  if input.profile == .forwardOnly && (leftAbsent || rightAbsent) then
    .fault .unsupportedInProfile
  else
    let backsolve := (input.memory input.output).written && (leftAbsent != rightAbsent)
    let prepared : Except Fault Mem :=
      if backsolve then
        let knownAddress := if leftAbsent then input.right else input.left
        let missingAddress := if leftAbsent then input.left else input.right
        let known := (input.memory knownAddress).value
        if isXor then
          match writeOnce input.memory missingAddress
              ((input.memory input.output).value ^^^ known) with
          | some memory => .ok memory
          | none => .error .writeConflict
        else if known == 0#128 then
          .error .mulBacksolveZero
        else if !input.proposedInverse.written ||
            GHASH128.mul known input.proposedInverse.value != 1#128 then
          .error .badInverse
        else
          match writeOnce input.memory missingAddress
              (GHASH128.mul (input.memory input.output).value input.proposedInverse.value) with
          | some memory => .ok memory
          | none => .error .writeConflict
      else
        .ok input.memory
    match prepared with
    | .error fault => .fault fault
    | .ok memory =>
        let value := if isXor then
          (memory input.left).value ^^^ (memory input.right).value
        else
          GHASH128.mul (memory input.left).value (memory input.right).value
        finishWrite input.common memory input.output value

/-- Pure endpoint decision for every full-profile instruction kind. -/
def decide : Instruction -> Decision
  | .set common memory address constant => finishWrite common memory address constant
  | .xor input => finishBinary true input
  | .mul input => finishBinary false input
  | .deref mode input =>
      if input.prepared.control != input.common.control then
        .fault .stateMismatch
      else if !(input.memory input.prepared.pointerAddress).written ||
          (input.memory input.prepared.pointerAddress).value != encodeIndex input.prepared.base then
        .fault (.deref .unresolvedPointer)
      else if mode == .cell && input.profile == .forwardOnly &&
          !(input.memory input.prepared.localAddress).written then
        .fault .unsupportedInProfile
      else
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
          common := input.common, nextControl := control, memory := input.memory }
      | .fault reason => .fault (.jump reason)
  | .blake3 request =>
      match advance request.common with
      | none => .fault .address
      | some nextControl => .serviceRequired { request, nextControl }

/-- A service response is accepted only by the request that created it. -/
def finishBlake3 (pending : ServicePending) (response : Blake3Response) : Decision :=
  let request := pending.request
  if response.txnId != request.common.txnId || response.serviceId != request.serviceId then
    .fault .badService
  else
    match writeOnce request.memory request.outputAddresses.1 response.digest.1 with
    | none => .fault .writeConflict
    | some memory =>
        match writeOnce memory request.outputAddresses.2 response.digest.2 with
        | none => .fault .writeConflict
        | some memory => .result {
            common := request.common, nextControl := pending.nextControl, memory := memory }

def serviceResponseMatches (pending : ServicePending) (response : Blake3Response) : Bool :=
  response.txnId == pending.request.common.txnId &&
    response.serviceId == pending.request.serviceId

inductive ServiceState where
  /-- The next endpoint-owned identifier; callers cannot choose the live ID. -/
  | idle (nextServiceId : UInt32)
  /-- The sequence advances when a request is accepted and survives abort. -/
  | pending (nextServiceId : UInt32) (request : ServicePending)

inductive ServiceCommand where
  | start (request : Blake3Start)
  | respond (response : Blake3Response)
  | abort
  | reset

structure ServiceOutcome where
  state : ServiceState
  decision : Option Decision := none

/-- Linear service controller: only a live pending request may consume one response. -/
def serviceStep : ServiceState -> ServiceCommand -> ServiceOutcome
  | .idle nextServiceId, .reset => { state := .idle nextServiceId }
  | .pending nextServiceId _, .reset => { state := .idle nextServiceId }
  | .idle nextServiceId, .abort => { state := .idle nextServiceId }
  | .pending nextServiceId _, .abort => { state := .idle nextServiceId }
  | .idle nextServiceId, .start start =>
      let assigned := start.assignServiceId nextServiceId
      match decide (.blake3 assigned) with
      | .serviceRequired pending => {
          state := .pending (nextServiceId + 1) pending,
          decision := some (.serviceRequired pending) }
      | decision => { state := .idle nextServiceId, decision := some decision }
  | .pending nextServiceId pending, .respond response =>
      if serviceResponseMatches pending response then {
        state := .idle nextServiceId, decision := some (finishBlake3 pending response) }
      else {
        state := .pending nextServiceId pending, decision := some (.fault .badService) }
  | .idle nextServiceId, .respond _ => {
      state := .idle nextServiceId, decision := some (.fault .badService) }
  | .pending nextServiceId pending, .start _ => {
      state := .pending nextServiceId pending, decision := some (.fault .stateMismatch) }

def transitionOf (effect : Effect) : Transaction.Transition := {
  txnId := effect.common.txnId
  currentPc := UInt32.ofNat effect.common.control.pc
  currentFp := UInt32.ofNat effect.common.control.fp
  nextPc := UInt32.ofNat effect.nextControl.pc
  nextFp := UInt32.ofNat effect.nextControl.fp
  resultChecksum := effect.common.resultChecksum
}

/-- Every canonical control index survives the packet lifecycle's `UInt32` boundary. -/
def Representable (effect : Effect) : Prop :=
  CheckedIndex.valid effect.common.control.pc /\
    CheckedIndex.valid effect.common.control.fp /\
    CheckedIndex.valid effect.nextControl.pc /\
    CheckedIndex.valid effect.nextControl.fp

/--
Non-vacuous bridge: a representable functional result is accepted into the
actual pending state, rather than merely being presented to a rejecting stage.
-/
def stages (model : Transaction.Model) (instruction : Instruction)
    (outcome : Transaction.Outcome) : Prop :=
  exists effect, decide instruction = .result effect /\
    Representable effect /\
    outcome = Transaction.step model (.stage (transitionOf effect)) /\
    outcome.model.state = .resultPending (transitionOf effect)

theorem decided_result_stages (model : Transaction.Model) (instruction : Instruction)
    (effect : Effect) (hdecide : decide instruction = .result effect)
    (hrepresentable : Representable effect)
    (hidle : model.state = .idle)
    (hrange : Transaction.currentIndicesInRange (transitionOf effect) = true)
    (hmatch : Transaction.stateMatches model (transitionOf effect) = true) :
    stages model instruction
      (Transaction.step model (.stage (transitionOf effect))) := by
  have hstage := Transaction.stage_is_atomic model (transitionOf effect)
    hidle hrange hmatch
  refine ⟨effect, hdecide, hrepresentable, rfl, ?_⟩
  rw [hstage]

theorem staged_result_matching_retire_commits (model : Transaction.Model)
    (instruction : Instruction) (effect : Effect)
    (hdecide : decide instruction = .result effect)
    (hrepresentable : Representable effect)
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
  · exact decided_result_stages model instruction effect hdecide hrepresentable
      hidle hrange hmatch
  · rw [hstage]
    simp [Transaction.step, transitionOf]

theorem staged_result_abort_never_commits (model : Transaction.Model)
    (instruction : Instruction) (effect : Effect)
    (hdecide : decide instruction = .result effect)
    (hrepresentable : Representable effect)
    (hidle : model.state = .idle)
    (hrange : Transaction.currentIndicesInRange (transitionOf effect) = true)
    (hmatch : Transaction.stateMatches model (transitionOf effect) = true) :
    stages model instruction (Transaction.step model (.stage (transitionOf effect))) /\
      (Transaction.step
        (Transaction.step model (.stage (transitionOf effect))).model .abort).model.committed =
        (Transaction.step model (.stage (transitionOf effect))).model.committed := by
  constructor
  · exact decided_result_stages model instruction effect hdecide hrepresentable
      hidle hrange hmatch
  · exact Transaction.abort_preserves_committed _

theorem staged_result_reset_restores_initial (model : Transaction.Model)
    (instruction : Instruction) (effect : Effect)
    (hdecide : decide instruction = .result effect)
    (hrepresentable : Representable effect)
    (hidle : model.state = .idle)
    (hrange : Transaction.currentIndicesInRange (transitionOf effect) = true)
    (hmatch : Transaction.stateMatches model (transitionOf effect) = true) :
    let staged := Transaction.step model (.stage (transitionOf effect))
    stages model instruction staged /\
      (Transaction.step staged.model .reset).model = Transaction.initial := by
  dsimp
  constructor
  · exact decided_result_stages model instruction effect hdecide hrepresentable
      hidle hrange hmatch
  · exact Transaction.reset_restores_initial _

theorem staged_result_matching_retire_is_exactly_once (model : Transaction.Model)
    (instruction : Instruction) (effect : Effect)
    (hdecide : decide instruction = .result effect)
    (hrepresentable : Representable effect)
    (hidle : model.state = .idle)
    (hrange : Transaction.currentIndicesInRange (transitionOf effect) = true)
    (hmatch : Transaction.stateMatches model (transitionOf effect) = true) :
    let staged := Transaction.step model (.stage (transitionOf effect))
    let first := Transaction.step staged.model
      (.retire effect.common.txnId effect.common.resultChecksum)
    let second := Transaction.step first.model
      (.retire effect.common.txnId effect.common.resultChecksum)
    stages model instruction staged /\
      first.retired = true /\ second.retired = false /\
      second.fault = some .badState /\
      second.model.committed = first.model.committed := by
  have hstage := Transaction.stage_is_atomic model (transitionOf effect)
    hidle hrange hmatch
  dsimp
  constructor
  · exact decided_result_stages model instruction effect hdecide hrepresentable
      hidle hrange hmatch
  · rw [hstage]
    simpa [transitionOf] using
      (Transaction.matching_retire_is_exactly_once model (transitionOf effect))

theorem blake3_never_decides_digest (request : Blake3Request) (nextControl : Control)
    (hadvance : advance request.common = some nextControl) :
    decide (.blake3 request) = .serviceRequired { request, nextControl } := by
  simp [decide, hadvance]

theorem blake3_rejects_pc_overflow_before_service (request : Blake3Request)
    (hoverflow : advance request.common = none) :
    decide (.blake3 request) = .fault .address := by
  simp [decide, hoverflow]

theorem service_start_assigns_endpoint_id (start : Blake3Start)
    (serviceId : UInt32) (nextControl : Control)
    (hadvance : advance start.common = some nextControl) :
    let request := start.assignServiceId serviceId
    let pending : ServicePending := { request, nextControl }
    serviceStep (.idle serviceId) (.start start) = {
      state := .pending (serviceId + 1) pending
      decision := some (.serviceRequired pending) } := by
  simp [serviceStep, Blake3Start.assignServiceId, decide, hadvance]

theorem blake3_rejects_wrong_transaction (pending : ServicePending)
    (response : Blake3Response)
    (h : response.txnId != pending.request.common.txnId) :
    finishBlake3 pending response = .fault .badService := by
  simp [finishBlake3, h]

theorem blake3_rejects_wrong_service (pending : ServicePending)
    (response : Blake3Response)
    (h : response.serviceId != pending.request.serviceId) :
    finishBlake3 pending response = .fault .badService := by
  simp [finishBlake3, h]

theorem finishWrite_rejects_pc_overflow (common : Common) (memory : Mem)
    (address : Index) (value : Word) (h : advance common = none) :
    finishWrite common memory address value = .fault .address := by
  simp [finishWrite, h]

theorem blake3_rejects_first_output_conflict (pending : ServicePending)
    (response : Blake3Response)
    (htxn : response.txnId = pending.request.common.txnId)
    (hservice : response.serviceId = pending.request.serviceId)
    (hconflict : writeOnce pending.request.memory pending.request.outputAddresses.1
      response.digest.1 = none) :
    finishBlake3 pending response = .fault .writeConflict := by
  simp [finishBlake3, htxn, hservice, hconflict]

theorem blake3_rejects_second_output_conflict (pending : ServicePending)
    (response : Blake3Response) (memory : Mem)
    (htxn : response.txnId = pending.request.common.txnId)
    (hservice : response.serviceId = pending.request.serviceId)
    (hfirst : writeOnce pending.request.memory pending.request.outputAddresses.1
      response.digest.1 = some memory)
    (hconflict : writeOnce memory pending.request.outputAddresses.2
      response.digest.2 = none) :
    finishBlake3 pending response = .fault .writeConflict := by
  simp [finishBlake3, htxn, hservice, hfirst, hconflict]

theorem service_response_consumes_pending (nextServiceId : UInt32)
    (pending : ServicePending)
    (response : Blake3Response)
    (hmatch : serviceResponseMatches pending response = true) :
    (serviceStep (.pending nextServiceId pending) (.respond response)).state =
      .idle nextServiceId := by
  simp [serviceStep, hmatch]

theorem mismatched_service_response_preserves_pending (nextServiceId : UInt32)
    (pending : ServicePending)
    (response : Blake3Response)
    (hmismatch : serviceResponseMatches pending response = false) :
    serviceStep (.pending nextServiceId pending) (.respond response) = {
      state := .pending nextServiceId pending,
      decision := some (.fault .badService) } := by
  simp [serviceStep, hmismatch]

theorem service_replay_is_rejected (nextServiceId : UInt32) (pending : ServicePending)
    (first replay : Blake3Response)
    (hmatch : serviceResponseMatches pending first = true) :
    let consumed := serviceStep (.pending nextServiceId pending) (.respond first)
    (serviceStep consumed.state (.respond replay)).decision = some (.fault .badService) := by
  simp [serviceStep, hmatch]

theorem service_abort_rejects_late_response (nextServiceId : UInt32)
    (pending : ServicePending)
    (response : Blake3Response) :
    let aborted := serviceStep (.pending nextServiceId pending) .abort
    (serviceStep aborted.state (.respond response)).decision = some (.fault .badService) := by
  rfl

theorem service_reset_rejects_late_response (nextServiceId : UInt32)
    (pending : ServicePending)
    (response : Blake3Response) :
    let reset := serviceStep (.pending nextServiceId pending) .reset
    (serviceStep reset.state (.respond response)).decision = some (.fault .badService) := by
  rfl

theorem service_reset_preserves_sequence (nextServiceId : UInt32)
    (pending : ServicePending) :
    (serviceStep (.pending nextServiceId pending) .reset).state =
      .idle nextServiceId := by
  rfl

theorem xor_uses_supplied_operands (input : BinaryInput) :
    decide (.xor input) = finishBinary true input := by
  rfl

theorem mul_uses_canonical_ghash (input : BinaryInput) :
    decide (.mul input) = finishBinary false input := by
  rfl

theorem mul_forward_uses_canonical_ghash (input : BinaryInput)
    (hleft : (input.memory input.left).written = true)
    (hright : (input.memory input.right).written = true) :
    decide (.mul input) = finishWrite input.common input.memory input.output
      (GHASH128.mul (input.memory input.left).value
        (input.memory input.right).value) := by
  simp [decide, finishBinary, hleft, hright]

theorem forward_only_rejects_absent_left (isXor : Bool) (input : BinaryInput)
    (hprofile : input.profile = .forwardOnly)
    (hleft : (input.memory input.left).written = false) :
    finishBinary isXor input = .fault .unsupportedInProfile := by
  simp [finishBinary, hprofile, hleft]

theorem forward_only_rejects_absent_right (isXor : Bool) (input : BinaryInput)
    (hprofile : input.profile = .forwardOnly)
    (hright : (input.memory input.right).written = false) :
    finishBinary isXor input = .fault .unsupportedInProfile := by
  simp [finishBinary, hprofile, hright]

theorem mul_backsolve_rejects_zero (input : BinaryInput)
    (hprofile : input.profile = .interpreterCompat)
    (hleft : (input.memory input.left).written = false)
    (hright : (input.memory input.right).written = true)
    (houtput : (input.memory input.output).written = true)
    (hzero : (input.memory input.right).value = 0#128) :
    decide (.mul input) = .fault .mulBacksolveZero := by
  simp [decide, finishBinary, hprofile, hleft, hright, houtput, hzero]

theorem mul_backsolve_rejects_unverified_inverse (input : BinaryInput)
    (hprofile : input.profile = .interpreterCompat)
    (hleft : (input.memory input.left).written = false)
    (hright : (input.memory input.right).written = true)
    (houtput : (input.memory input.output).written = true)
    (hknown : (input.memory input.right).value ≠ 0#128)
    (hinverse : input.proposedInverse.written = false) :
    decide (.mul input) = .fault .badInverse := by
  simp [decide, finishBinary, hprofile, hleft, hright, houtput, hknown, hinverse]

theorem deref_uses_canonical_control (mode : DerefMode) (input : DerefInput) :
    decide (.deref mode input) =
      if input.prepared.control != input.common.control then
        .fault .stateMismatch
      else if !(input.memory input.prepared.pointerAddress).written ||
          (input.memory input.prepared.pointerAddress).value != encodeIndex input.prepared.base then
        .fault (.deref .unresolvedPointer)
      else if mode == .cell && input.profile == .forwardOnly &&
          !(input.memory input.prepared.localAddress).written then
        .fault .unsupportedInProfile
      else
        match executeDeref encodeIndex mode input.memory input.prepared with
        | .ok control memory => .result {
            common := input.common, nextControl := control, memory := memory }
        | .deferred control left right memory => .result {
            common := input.common, nextControl := control, memory := memory
            deferred := [(left, right)] }
        | .fault reason => .fault (.deref reason) := by
  rfl

theorem deref_rejects_prepared_control_mismatch (mode : DerefMode)
    (input : DerefInput)
    (h : input.prepared.control != input.common.control) :
    decide (.deref mode input) = .fault .stateMismatch := by
  simp [decide, h]

theorem forward_only_deref_cell_requires_local (input : DerefInput)
    (hprofile : input.profile = .forwardOnly)
    (hlocal : (input.memory input.prepared.localAddress).written = false)
    (hcontrol : input.prepared.control = input.common.control)
    (hpointer : (input.memory input.prepared.pointerAddress).written = true)
    (hvalue : (input.memory input.prepared.pointerAddress).value =
      encodeIndex input.prepared.base) :
    decide (.deref .cell input) = .fault .unsupportedInProfile := by
  simp [decide, hprofile, hlocal, hcontrol, hpointer, hvalue]

theorem deref_pointer_fault_precedes_profile_guard (input : DerefInput)
    (hcontrol : input.prepared.control = input.common.control)
    (hpointer : (input.memory input.prepared.pointerAddress).written = false) :
    decide (.deref .cell input) = .fault (.deref .unresolvedPointer) := by
  simp [decide, hcontrol, hpointer]

theorem jump_uses_canonical_control (input : JumpInput) :
    decide (.jump input) =
      match ControlPrimitives.jump encodeIndex input.common.control input.condition
          input.targetPcWord input.targetFpWord input.inverseWitness input.resolvedTargets with
      | .ok control => .result {
          common := input.common, nextControl := control, memory := input.memory }
      | .fault reason => .fault (.jump reason) := by
  rfl

theorem jump_success_preserves_memory (input : JumpInput) (control : Control)
    (h : ControlPrimitives.jump encodeIndex input.common.control input.condition
      input.targetPcWord input.targetFpWord input.inverseWitness
      input.resolvedTargets = .ok control) :
    decide (.jump input) = .result {
      common := input.common, nextControl := control, memory := input.memory } := by
  simp [decide, h]

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

example : stages Transaction.initial
    (.set witnessCommon Memory.empty 12 (0x2a#128))
    (Transaction.step Transaction.initial (.stage (transitionOf witnessSetEffect))) := by
  exact decided_result_stages Transaction.initial
    (.set witnessCommon Memory.empty 12 (0x2a#128)) witnessSetEffect rfl
    (by simp [Representable, CheckedIndex.valid, witnessSetEffect, witnessCommon,
      CheckedIndex.max]) rfl (by decide) (by decide)

example : exists request pending, decide (.blake3 request) = .serviceRequired pending := by
  let request : Blake3Request := {
    common := witnessCommon, serviceId := 11, memory := Memory.empty,
    inputWords := fun _ => 0#128, chainingValue := fun _ => 0#128,
    outputAddresses := (20, 21), metadata := fun _ => 0 }
  refine ⟨request, { request, nextControl := { pc := 4, fp := 9 } },
    blake3_never_decides_digest request { pc := 4, fp := 9 } ?_⟩
  decide

def witnessBinary : BinaryInput := {
  common := witnessCommon, profile := .interpreterCompat,
  memory := Memory.empty, left := 1, right := 2, output := 3,
  proposedInverse := { written := false, value := 0#128 } }

def witnessZeroEffect : Effect where
  common := witnessCommon
  nextControl := { pc := 4, fp := 9 }
  memory := writeRaw Memory.empty 3 (0#128)

def witnessXorBacksolveMemory : Mem :=
  writeRaw (writeRaw Memory.empty 2 (0x12#128)) 3 (0x34#128)

def witnessXorBacksolve : BinaryInput := {
  common := witnessCommon, profile := .interpreterCompat,
  memory := witnessXorBacksolveMemory, left := 1, right := 2, output := 3,
  proposedInverse := { written := false, value := 0#128 } }

def witnessXorBacksolveEffect : Effect where
  common := witnessCommon
  nextControl := { pc := 4, fp := 9 }
  memory := writeRaw (writeRaw witnessXorBacksolveMemory 1 (0x26#128)) 3 (0x34#128)

example : decide (.xor witnessXorBacksolve) = .result witnessXorBacksolveEffect := by
  rfl

example : exists effect, decide (.xor witnessBinary) = .result effect := by
  refine ⟨witnessZeroEffect, ?_⟩
  rfl

example : exists effect, decide (.mul witnessBinary) = .result effect := by
  refine ⟨witnessZeroEffect, ?_⟩
  rfl

def witnessJump : JumpInput := {
  common := witnessCommon, memory := Memory.empty,
  condition := 0#128, targetPcWord := 0#128,
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
#print axioms staged_result_reset_restores_initial
#print axioms staged_result_matching_retire_is_exactly_once
#print axioms blake3_never_decides_digest
#print axioms blake3_rejects_pc_overflow_before_service
#print axioms service_start_assigns_endpoint_id
#print axioms finishWrite_rejects_pc_overflow
#print axioms blake3_rejects_first_output_conflict
#print axioms blake3_rejects_second_output_conflict
#print axioms service_response_consumes_pending
#print axioms mismatched_service_response_preserves_pending
#print axioms service_replay_is_rejected
#print axioms service_abort_rejects_late_response
#print axioms service_reset_rejects_late_response
#print axioms service_reset_preserves_sequence
#print axioms mul_uses_canonical_ghash
#print axioms mul_forward_uses_canonical_ghash
#print axioms forward_only_rejects_absent_left
#print axioms forward_only_rejects_absent_right
#print axioms mul_backsolve_rejects_zero
#print axioms mul_backsolve_rejects_unverified_inverse
#print axioms deref_uses_canonical_control
#print axioms deref_rejects_prepared_control_mismatch
#print axioms forward_only_deref_cell_requires_local
#print axioms deref_pointer_fault_precedes_profile_guard
#print axioms jump_uses_canonical_control
#print axioms jump_success_preserves_memory

end LeanVMBMinCore.FullProfile

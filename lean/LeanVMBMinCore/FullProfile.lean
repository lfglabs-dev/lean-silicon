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

inductive Fault where
  | address
  | badState
  | stateMismatch
  | unsupportedInProfile
  | badInverse
  | mulBacksolveZero
  | aliasInconsistent
  | writeConflict
  | badCell
  | deref (reason : ControlPrimitives.Fault)
  | jump (reason : ControlPrimitives.Fault)
  | badService
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
  /-- Condition, destination, and frame addresses in frozen access order. -/
  accesses : Fin 3 -> Index

structure Blake3Request where
  common : Common
  serviceId : UInt32
  /-- Retained request kind; BLAKE3 compression is protocol value one. -/
  serviceKind : UInt8
  memory : Mem
  /-- BLAKE3 compression has exactly four message words. -/
  inputWords : Fin 4 -> Word
  /-- BLAKE3 compression has exactly two chaining-value words. -/
  chainingValue : Fin 2 -> Word
  outputAddresses : Index × Index
  /-- Frozen access order reported in the completed result payload. -/
  accesses : Fin 8 -> Index
  /-- Counter, block length, and flags occupy exactly sixteen bytes. -/
  metadata : Fin 16 -> UInt8

/-- Host-owned BLAKE3 inputs before the endpoint assigns a service identifier. -/
structure Blake3Start where
  common : Common
  memory : Mem
  inputWords : Fin 4 -> Word
  chainingValue : Fin 2 -> Word
  outputAddresses : Index × Index
  accesses : Fin 8 -> Index
  metadata : Fin 16 -> UInt8

/-- Raw packet fields, before metadata and effective-address validation. -/
structure RawBlake3Request where
  common : Common
  messageOffsets : Fin 4 -> Index
  cvOffset : Index
  outOffset : Index
  metadata : Word
  messageCells : Fin 4 -> Cell
  cvCells : Fin 2 -> Cell
  outCells : Fin 2 -> Cell

def metadataByte (metadata : Word) (i : Fin 16) : UInt8 :=
  UInt8.ofNat ((metadata.toNat / 2 ^ (8 * i.val)) % 256)

def metadataBlockLength (metadata : Word) : Nat :=
  (metadata.toNat / 2 ^ 64) % 2 ^ 32

def metadataFlags (metadata : Word) : Nat :=
  metadata.toNat / 2 ^ 96

def validBlake3Metadata (metadata : Word) : Bool :=
  metadataBlockLength metadata <= 64 && metadataFlags metadata < 128

/-- The packet decoder's canonical cell rule: absence carries no hidden value. -/
def canonicalCell (cell : Cell) : Bool :=
  cell.written || cell.value == 0#128

/-- Validate every raw BLAKE3 cell before interpreting any instruction field. -/
def canonicalBlake3Cells (raw : RawBlake3Request) : Bool :=
  canonicalCell (raw.messageCells 0) && canonicalCell (raw.messageCells 1) &&
    canonicalCell (raw.messageCells 2) && canonicalCell (raw.messageCells 3) &&
    canonicalCell (raw.cvCells 0) && canonicalCell (raw.cvCells 1) &&
    canonicalCell (raw.outCells 0) && canonicalCell (raw.outCells 1)

def putSuppliedCell (memory : Mem) (address : Index) (cell : Cell) : Mem :=
  fun query => if query = address then cell else memory query

def suppliedAliasesAgree (cells : List (Index × Cell)) : Bool :=
  match cells with
  | [] => true
  | (address, cell) :: rest =>
      rest.all (fun other => other.1 != address || other.2 == cell) &&
        suppliedAliasesAgree rest

def materializeSupplied (cells : List (Index × Cell)) : Mem :=
  cells.foldl (fun memory supplied => putSuppliedCell memory supplied.1 supplied.2)
    Memory.empty

abbrev Blake3Addresses := Index × Index × Index × Index × Index × Index × Index × Index

def prepareBlake3Addresses (raw : RawBlake3Request) : Except Fault Blake3Addresses :=
  match CheckedIndex.add raw.common.control.fp (raw.messageOffsets 0) with
  | none => .error .address
  | some in0 => match CheckedIndex.add raw.common.control.fp (raw.messageOffsets 1) with
    | none => .error .address
    | some in1 => match CheckedIndex.add raw.common.control.fp (raw.messageOffsets 2) with
      | none => .error .address
      | some in2 => match CheckedIndex.add raw.common.control.fp (raw.messageOffsets 3) with
        | none => .error .address
        | some in3 => match CheckedIndex.add raw.common.control.fp raw.cvOffset with
          | none => .error .address
          | some cv0 => match CheckedIndex.add cv0 1 with
            | none => .error .address
            | some cv1 => match CheckedIndex.add raw.common.control.fp raw.outOffset with
              | none => .error .address
              | some out0 => match CheckedIndex.add out0 1 with
                | none => .error .address
                | some out1 => .ok (in0, in1, in2, in3, cv0, cv1, out0, out1)

def prepareValidBlake3 (raw : RawBlake3Request) : Except Fault Blake3Start :=
  match prepareBlake3Addresses raw with
  | .error fault => .error fault
  | .ok (in0, in1, in2, in3, cv0, cv1, out0, out1) =>
    let supplied := [(in0, raw.messageCells 0), (in1, raw.messageCells 1),
      (in2, raw.messageCells 2), (in3, raw.messageCells 3),
      (cv0, raw.cvCells 0), (cv1, raw.cvCells 1),
      (out0, raw.outCells 0), (out1, raw.outCells 1)]
    if suppliedAliasesAgree supplied then
      let memory := materializeSupplied supplied
      .ok {
      common := raw.common
      memory
      inputWords := fun i => (memory ([in0, in1, in2, in3].get i)).value
      chainingValue := fun i => (memory ([cv0, cv1].get i)).value
      outputAddresses := (out0, out1)
      accesses := fun i => ([in0, in1, in2, in3, cv0, cv1, out0, out1].get i)
      metadata := metadataByte raw.metadata }
    else .error .aliasInconsistent

def prepareBlake3 (raw : RawBlake3Request) : Except Fault Blake3Start :=
  if !canonicalBlake3Cells raw then .error .badCell
  else if validBlake3Metadata raw.metadata then prepareValidBlake3 raw
  else .error .badService

def Blake3Start.assignServiceId (start : Blake3Start)
    (serviceId : UInt32) : Blake3Request := {
  common := start.common
  serviceId
  serviceKind := 1
  memory := start.memory
  inputWords := start.inputWords
  chainingValue := start.chainingValue
  outputAddresses := start.outputAddresses
  accesses := start.accesses
  metadata := start.metadata }

structure Blake3Response where
  txnId : Transaction.TxnId
  serviceId : UInt32
  serviceKind : UInt8
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

structure Effect where
  common : Common
  nextControl : Control
  /-- Supplied memory before this instruction's write-once effects. -/
  initialMemory : Mem := Memory.empty
  memory : Mem
  deferred : List (Index × Index) := []
  /-- Addresses touched by the instruction in executable-model order. -/
  accesses : List Index := []
  /-- Explicit write order when it cannot be recovered from operand access order. -/
  orderedWrites : Option (List (Index × Word)) := none

inductive Decision where
  | result (effect : Effect)
  | serviceRequired (pending : ServicePending)
  | fault (reason : Fault)

def advance (common : Common) : Option Control := do
  let pc <- checkedOffset common.control.pc 1
  some { common.control with pc := pc }

def finishWrite (common : Common) (memory : Mem) (address : Index)
    (value : Word) : Decision :=
  match writeOnce memory address value with
  | none => .fault .writeConflict
  | some memory' =>
      match advance common with
      | none => .fault .address
      | some next => .result {
          common, nextControl := next, initialMemory := memory, memory := memory'
          accesses := [address] }

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
        match finishWrite input.common memory input.output value with
        | .result effect => .result {
            common := effect.common, nextControl := effect.nextControl
            initialMemory := input.memory, memory := effect.memory
            deferred := effect.deferred
            accesses := [input.left, input.right, input.output] }
        | decision => decision

/-- Pure endpoint decision for every full-profile instruction kind. -/
def decide : Instruction -> Decision
  | .set common memory address constant => finishWrite common memory address constant
  | .xor input => finishBinary true input
  | .mul input => finishBinary false input
  | .deref mode input =>
      if input.prepared.control != input.common.control then
        .fault .stateMismatch
      else if input.prepared.base >= 2 ^ 16 then
        .fault .address
      else if !(input.memory input.prepared.pointerAddress).written ||
          (input.memory input.prepared.pointerAddress).value != encodeIndex input.prepared.base then
        .fault (.deref .unresolvedPointer)
      else if mode == .cell && input.profile == .forwardOnly &&
          !(input.memory input.prepared.localAddress).written then
        .fault .unsupportedInProfile
      else
        match executeDeref encodeIndex mode input.memory input.prepared with
        | .ok control memory => .result {
            common := input.common, nextControl := control
            initialMemory := input.memory, memory := memory
            accesses := [input.prepared.pointerAddress, input.prepared.target,
              input.prepared.localAddress] }
        | .deferred control left right memory => .result {
            common := input.common, nextControl := control
            initialMemory := input.memory, memory := memory
            deferred := [(left, right)]
            accesses := [input.prepared.pointerAddress, input.prepared.target,
              input.prepared.localAddress] }
        | .fault reason => .fault (.deref reason)
  | .jump input =>
      match ControlPrimitives.jump encodeIndex
          input.common.control input.condition input.targetPcWord input.targetFpWord
          input.inverseWitness input.resolvedTargets with
      | .ok control => .result {
          common := input.common, nextControl := control
          initialMemory := input.memory, memory := input.memory
          accesses := List.ofFn input.accesses }
      | .fault reason => .fault (.jump reason)
  | .blake3 request =>
      match advance request.common with
      | none => .fault .address
      | some nextControl => .serviceRequired { request, nextControl }

/-- A service response is accepted only by the request that created it. -/
def u32leBytes (value : UInt32) : List UInt8 :=
  (List.range 4).map fun i => UInt8.ofNat ((value.toNat / 2 ^ (8 * i)) % 256)

def wordLEBytes (value : Word) : List UInt8 :=
  (List.range 16).map fun i => UInt8.ofNat ((value.toNat / 2 ^ (8 * i)) % 256)

def crc32Bit (crc : UInt32) : UInt32 :=
  if crc.land 1 != 0 then (crc.shiftRight 1).xor 0xedb88320
  else crc.shiftRight 1

def crc32Byte (crc : UInt32) (byte : UInt8) : UInt32 :=
  (List.range 8).foldl (fun value _ => crc32Bit value)
    (crc.xor (UInt32.ofNat byte.toNat))

/-- IEEE 802.3 reflected CRC-32 used by RETIRE over the result payload alone. -/
def crc32 (payload : List UInt8) : UInt32 :=
  (payload.foldl crc32Byte 0xffffffff).xor 0xffffffff

def encodeBlake3Write (write : Index × Word) : List UInt8 :=
  u32leBytes (UInt32.ofNat write.1) ++ wordLEBytes write.2

/-- Writes emitted by the executable write-once frame, in frozen order. -/
def blake3ResultWrites (pending : ServicePending)
    (response : Blake3Response) : List (Index × Word) :=
  let request := pending.request
  let first := request.outputAddresses.1
  let second := request.outputAddresses.2
  let writes := if (request.memory first).written then [] else [(first, response.digest.1)]
  let afterFirst := writeRaw request.memory first response.digest.1
  if (afterFirst second).written then writes else writes ++ [(second, response.digest.2)]

/-- Byte-exact completed BLAKE3 result payload from protocol section 8.1. -/
def blake3ResultPayload (pending : ServicePending)
    (response : Blake3Response) : List UInt8 :=
  let writes := blake3ResultWrites pending response
  u32leBytes pending.request.common.txnId ++
    u32leBytes (UInt32.ofNat pending.nextControl.pc) ++
    u32leBytes (UInt32.ofNat pending.nextControl.fp) ++
    [UInt8.ofNat writes.length] ++ writes.flatMap encodeBlake3Write ++
    [0, 8] ++ (List.ofFn pending.request.accesses).flatMap
      (fun address => u32leBytes (UInt32.ofNat address))

def completedBlake3Common (pending : ServicePending)
    (response : Blake3Response) : Common :=
  { pending.request.common with resultChecksum := crc32 (blake3ResultPayload pending response) }

def finishBlake3 (pending : ServicePending) (response : Blake3Response) : Decision :=
  let request := pending.request
  if response.txnId != request.common.txnId || response.serviceId != request.serviceId ||
      response.serviceKind != request.serviceKind || request.serviceKind != 1 then
    .fault .badService
  else
    match writeOnce request.memory request.outputAddresses.1 response.digest.1 with
    | none => .fault .writeConflict
    | some memory =>
        match writeOnce memory request.outputAddresses.2 response.digest.2 with
        | none => .fault .writeConflict
        | some memory => .result {
            common := completedBlake3Common pending response
            nextControl := pending.nextControl
            initialMemory := request.memory, memory := memory
            accesses := List.ofFn request.accesses
            orderedWrites := some (blake3ResultWrites pending response) }

def serviceResponseMatches (pending : ServicePending) (response : Blake3Response) : Bool :=
  response.txnId == pending.request.common.txnId &&
    response.serviceId == pending.request.serviceId &&
    response.serviceKind == pending.request.serviceKind && pending.request.serviceKind == 1

inductive ServiceState where
  /-- The next endpoint-owned identifier; callers cannot choose the live ID. -/
  | idle (nextServiceId : UInt32)
  /-- The sequence advances when a request is accepted and survives abort. -/
  | pending (nextServiceId : UInt32) (request : ServicePending)

inductive ServiceCommand where
  | start (request : RawBlake3Request)
  | respond (response : Blake3Response)
  | abort
  | reset

structure ServiceOutcome where
  state : ServiceState
  decision : Option Decision := none

/-- Linear service controller: only a live pending request may consume one response. -/
def serviceStep : ServiceState -> ServiceCommand -> ServiceOutcome
  | .idle _, .reset => { state := .idle 1 }
  | .pending _ _, .reset => { state := .idle 1 }
  | .idle nextServiceId, .abort => { state := .idle nextServiceId }
  | .pending nextServiceId _, .abort => { state := .idle nextServiceId }
  | .idle nextServiceId, .start raw =>
      if nextServiceId == 0 || nextServiceId == 0xffffffff then
        { state := .idle nextServiceId, decision := some (.fault .badService) }
      else match prepareBlake3 raw with
        | .error fault => { state := .idle nextServiceId, decision := some (.fault fault) }
        | .ok start =>
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
      state := .idle nextServiceId, decision := some (.fault .badState) }
  | .pending nextServiceId pending, .start _ => {
      state := .pending nextServiceId pending, decision := some (.fault .badState) }

def effectWrites (effect : Effect) : List (Index × Word) :=
  match effect.orderedWrites with
  | some writes => writes
  | none => effect.accesses.foldl (fun writes address =>
      if writes.any (fun write => write.1 == address) then writes
      else if !(effect.initialMemory address).written && (effect.memory address).written then
        writes ++ [(address, (effect.memory address).value)]
      else writes) []

def encodeWrite (write : Index × Word) : List UInt8 :=
  u32leBytes (UInt32.ofNat write.1) ++ wordLEBytes write.2

def encodeDeferred (item : Index × Index) : List UInt8 :=
  u32leBytes (UInt32.ofNat item.1) ++ u32leBytes (UInt32.ofNat item.2)

/-- Byte-exact result payload shared by ordinary and service-completed effects. -/
def effectResultPayload (effect : Effect) : List UInt8 :=
  let writes := effectWrites effect
  u32leBytes effect.common.txnId ++
    u32leBytes (UInt32.ofNat effect.nextControl.pc) ++
    u32leBytes (UInt32.ofNat effect.nextControl.fp) ++
    [UInt8.ofNat writes.length] ++ writes.flatMap encodeWrite ++
    [UInt8.ofNat effect.deferred.length] ++ effect.deferred.flatMap encodeDeferred ++
    [UInt8.ofNat effect.accesses.length] ++ effect.accesses.flatMap
      (fun address => u32leBytes (UInt32.ofNat address))

def effectResultChecksum (effect : Effect) : Transaction.ResultChecksum :=
  crc32 (effectResultPayload effect)

def transitionOf (effect : Effect) : Transaction.Transition := {
  txnId := effect.common.txnId
  currentPc := UInt32.ofNat effect.common.control.pc
  currentFp := UInt32.ofNat effect.common.control.fp
  nextPc := UInt32.ofNat effect.nextControl.pc
  nextFp := UInt32.ofNat effect.nextControl.fp
  resultChecksum := effectResultChecksum effect
}

/-- Every canonical control index survives the packet lifecycle's `UInt32` boundary. -/
def protocolIndexLimit : Nat := 2 ^ 16

def ProtocolIndex (index : Index) : Prop := index < protocolIndexLimit

def Representable (effect : Effect) : Prop :=
  ProtocolIndex effect.common.control.pc /\
    ProtocolIndex effect.common.control.fp /\
    ProtocolIndex effect.nextControl.pc /\
    ProtocolIndex effect.nextControl.fp

def representableB (effect : Effect) : Bool :=
  effect.common.control.pc < protocolIndexLimit &&
    effect.common.control.fp < protocolIndexLimit &&
    effect.nextControl.pc < protocolIndexLimit &&
    effect.nextControl.fp < protocolIndexLimit

def commonControlRepresentableB (common : Common) : Bool :=
  common.control.pc < protocolIndexLimit && common.control.fp < protocolIndexLimit

def commonStateMatches (model : Transaction.Model) (common : Common) : Bool :=
  !model.stateValid ||
    (UInt32.ofNat common.control.pc == model.committed.pc &&
      UInt32.ofNat common.control.fp == model.committed.fp)

structure EndpointState where
  transaction : Transaction.Model
  service : ServiceState

def endpointInitial : EndpointState := {
  transaction := Transaction.initial, service := .idle 1 }

inductive EndpointCommand where
  | service (command : ServiceCommand)
  | retire (txnId : Transaction.TxnId) (checksum : Transaction.ResultChecksum)

structure EndpointOutcome where
  state : EndpointState
  decision : Option Decision := none
  transactionOutcome : Option Transaction.Outcome := none

/-- Compose service completion with the atomic stage/RETIRE lifecycle. -/
def endpointStep (state : EndpointState) : EndpointCommand -> EndpointOutcome
  | .service .reset => {
      state := endpointInitial
      transactionOutcome := some (Transaction.step state.transaction .reset) }
  | .service .abort =>
      let transaction := Transaction.step state.transaction .abort
      let service := serviceStep state.service .abort
      { state := { transaction := transaction.model, service := service.state }
        decision := service.decision, transactionOutcome := some transaction }
  | .service (.start raw) =>
      match state.service with
      | .pending nextServiceId pending =>
          let service := serviceStep (.pending nextServiceId pending) (.start raw)
          { state := { state with service := service.state }, decision := service.decision }
      | .idle nextServiceId =>
          if state.transaction.state != .idle then
            { state, decision := some (.fault .badState) }
          else if !commonStateMatches state.transaction raw.common then
            { state, decision := some (.fault .stateMismatch) }
          else if !commonControlRepresentableB raw.common then
            { state, decision := some (.fault .address) }
          else
            let service := serviceStep (.idle nextServiceId) (.start raw)
            { state := { state with service := service.state }, decision := service.decision }
  | .service (.respond response) =>
      match state.service with
      | .pending nextServiceId pending =>
          if serviceResponseMatches pending response then
            match finishBlake3 pending response with
            | .result effect =>
                if representableB effect then
                  let transaction := Transaction.step state.transaction
                    (.stage (transitionOf effect))
                  match transaction.fault with
                  | none =>
                    { state := {
                        transaction := transaction.model, service := .idle nextServiceId }
                      decision := some (.result effect)
                      transactionOutcome := some transaction }
                  | some .indexRange =>
                    { state := { state with service := .idle nextServiceId }
                      decision := some (.fault .address)
                      transactionOutcome := some transaction }
                  | some _ =>
                    { state := { state with service := .idle nextServiceId }
                      decision := some (.fault .stateMismatch)
                      transactionOutcome := some transaction }
                else
                  { state := { state with service := .idle nextServiceId }
                    decision := some (.fault .address) }
            | decision =>
                { state := { state with service := .idle nextServiceId }
                  decision := some decision }
          else
            { state, decision := some (.fault .badService) }
      | .idle _ => { state, decision := some (.fault .badState) }
  | .retire txnId checksum =>
      let transaction := Transaction.step state.transaction (.retire txnId checksum)
      { state := { state with transaction := transaction.model }
        transactionOutcome := some transaction }

theorem successful_service_response_stages (state : EndpointState)
    (nextServiceId : UInt32) (pending : ServicePending) (response : Blake3Response)
    (effect : Effect)
    (hservice : state.service = .pending nextServiceId pending)
    (hresponse : serviceResponseMatches pending response = true)
    (hfinish : finishBlake3 pending response = .result effect)
    (hrepresentable : representableB effect = true)
    (hidle : state.transaction.state = .idle)
    (hrange : Transaction.currentIndicesInRange (transitionOf effect) = true)
    (hstate : Transaction.stateMatches state.transaction (transitionOf effect) = true) :
    let outcome := endpointStep state (.service (.respond response))
    outcome.state.service = .idle nextServiceId /\
      outcome.state.transaction.state = .resultPending (transitionOf effect) /\
      outcome.decision = some (.result effect) := by
  cases state with
  | mk transaction service =>
    simp only at hservice
    subst service
    change transaction.state = .idle at hidle
    change Transaction.stateMatches transaction (transitionOf effect) = true at hstate
    have hstage := Transaction.stage_is_atomic transaction (transitionOf effect)
      hidle hrange hstate
    simp only [endpointStep, hresponse, hfinish, hrepresentable, ↓reduceIte]
    rw [hstage]
    simp

theorem successful_service_response_matching_retire_exactly_once
    (state : EndpointState) (nextServiceId : UInt32) (pending : ServicePending)
    (response : Blake3Response) (effect : Effect)
    (hservice : state.service = .pending nextServiceId pending)
    (hresponse : serviceResponseMatches pending response = true)
    (hfinish : finishBlake3 pending response = .result effect)
    (hrepresentable : representableB effect = true)
    (hidle : state.transaction.state = .idle)
    (hrange : Transaction.currentIndicesInRange (transitionOf effect) = true)
    (hstate : Transaction.stateMatches state.transaction (transitionOf effect) = true) :
    let completed := endpointStep state (.service (.respond response))
    let first := endpointStep completed.state
      (.retire effect.common.txnId (effectResultChecksum effect))
    let second := endpointStep first.state
      (.retire effect.common.txnId (effectResultChecksum effect))
    first.transactionOutcome.map (fun o => o.retired) = some true /\
      second.transactionOutcome.map (fun o => o.retired) = some false /\
      second.transactionOutcome.bind (fun o => o.fault) = some .badState /\
      second.state.transaction.committed = first.state.transaction.committed := by
  cases state with
  | mk transaction service =>
    simp only at hservice
    subst service
    change transaction.state = .idle at hidle
    change Transaction.stateMatches transaction (transitionOf effect) = true at hstate
    have hstage := Transaction.stage_is_atomic transaction (transitionOf effect)
      hidle hrange hstate
    simp only [endpointStep, hresponse, hfinish, hrepresentable, ↓reduceIte]
    rw [hstage]
    simp [endpointStep, Transaction.step, transitionOf]

theorem endpoint_reset_restores_protocol_initial (state : EndpointState) :
    (endpointStep state (.service .reset)).state = endpointInitial := by
  rfl

theorem service_start_requires_committed_control (state : EndpointState)
    (raw : RawBlake3Request) (nextServiceId : UInt32)
    (hservice : state.service = .idle nextServiceId)
    (hidle : state.transaction.state = .idle)
    (hmismatch : commonStateMatches state.transaction raw.common = false) :
    endpointStep state (.service (.start raw)) = {
      state, decision := some (.fault .stateMismatch) } := by
  simp [endpointStep, hservice, hidle, hmismatch]

/-- A live service is the outer endpoint state, so it masks neither state nor control faults. -/
theorem endpoint_pending_service_start_is_bad_state (state : EndpointState)
    (raw : RawBlake3Request) (nextServiceId : UInt32) (pending : ServicePending)
    (hservice : state.service = .pending nextServiceId pending) :
    endpointStep state (.service (.start raw)) = {
      state, decision := some (.fault .badState) } := by
  cases state with
  | mk transaction service =>
    simp only at hservice
    subst service
    rfl

theorem protocol_rejects_u16_boundary : ¬ ProtocolIndex (2 ^ 16) := by
  simp [ProtocolIndex, protocolIndexLimit]

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
      (.retire effect.common.txnId (effectResultChecksum effect))
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
      (.retire effect.common.txnId (effectResultChecksum effect))
    let second := Transaction.step first.model
      (.retire effect.common.txnId (effectResultChecksum effect))
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

theorem service_start_assigns_endpoint_id (raw : RawBlake3Request) (start : Blake3Start)
    (serviceId : UInt32) (nextControl : Control)
    (hprepare : prepareBlake3 raw = .ok start)
    (hnonzero : serviceId ≠ 0) (hnotmax : serviceId ≠ 0xffffffff)
    (hadvance : advance start.common = some nextControl) :
    let request := start.assignServiceId serviceId
    let pending : ServicePending := { request, nextControl }
    serviceStep (.idle serviceId) (.start raw) = {
      state := .pending (serviceId + 1) pending
      decision := some (.serviceRequired pending) } := by
  simp [serviceStep, hprepare, hnonzero, hnotmax, Blake3Start.assignServiceId,
    decide, hadvance]

theorem endpoint_rejects_out_of_range_control_before_service
    (raw : RawBlake3Request)
    (hout : raw.common.control.pc >= protocolIndexLimit ∨
      raw.common.control.fp >= protocolIndexLimit) :
    endpointStep endpointInitial (.service (.start raw)) = {
      state := endpointInitial, decision := some (.fault .address) } := by
  rcases hout with hpc | hfp
  · have hnot : ¬raw.common.control.pc < protocolIndexLimit := Nat.not_lt.mpr hpc
    simp [endpointStep, endpointInitial, Transaction.initial, commonStateMatches,
      commonControlRepresentableB, hnot]
  · have hnot : ¬raw.common.control.fp < protocolIndexLimit := Nat.not_lt.mpr hfp
    by_cases hpc : raw.common.control.pc < protocolIndexLimit
    · simp [endpointStep, endpointInitial, Transaction.initial, commonStateMatches,
        commonControlRepresentableB, hpc, hnot]
    · simp [endpointStep, endpointInitial, Transaction.initial, commonStateMatches,
        commonControlRepresentableB, hpc]

theorem malformed_blake3_metadata_is_rejected (raw : RawBlake3Request)
    (hcells : canonicalBlake3Cells raw = true)
    (hbad : validBlake3Metadata raw.metadata = false) :
    prepareBlake3 raw = .error .badService := by
  simp [prepareBlake3, hcells, hbad]

theorem noncanonical_blake3_cell_is_rejected (raw : RawBlake3Request)
    (hbad : canonicalBlake3Cells raw = false) :
    prepareBlake3 raw = .error .badCell := by
  simp [prepareBlake3, hbad]

theorem noncanonical_blake3_cell_precedes_metadata (raw : RawBlake3Request)
    (hcell : canonicalBlake3Cells raw = false)
    (_hmetadata : validBlake3Metadata raw.metadata = false) :
    prepareBlake3 raw = .error .badCell := by
  simp [prepareBlake3, hcell]

theorem blake3_assigned_kind_is_compress (start : Blake3Start) (serviceId : UInt32) :
    (start.assignServiceId serviceId).serviceKind = 1 := by
  rfl

theorem supplied_alias_presence_mismatch_is_rejected (address : Index)
    (present absent : Cell) (rest : List (Index × Cell))
    (hpresent : present.written = true) (habsent : absent.written = false) :
    suppliedAliasesAgree ((address, present) :: (address, absent) :: rest) = false := by
  have hne : absent ≠ present := by
    intro h
    have hwritten := congrArg Cell.written h
    simp [hpresent, habsent] at hwritten
  simp [suppliedAliasesAgree, hne]

theorem blake3_output_base_overflow_is_rejected (raw : RawBlake3Request)
    (hcells : canonicalBlake3Cells raw = true)
    (hmeta : validBlake3Metadata raw.metadata = true)
    (in0 in1 in2 in3 cv0 cv1 : Index)
    (h0 : CheckedIndex.add raw.common.control.fp (raw.messageOffsets 0) = some in0)
    (h1 : CheckedIndex.add raw.common.control.fp (raw.messageOffsets 1) = some in1)
    (h2 : CheckedIndex.add raw.common.control.fp (raw.messageOffsets 2) = some in2)
    (h3 : CheckedIndex.add raw.common.control.fp (raw.messageOffsets 3) = some in3)
    (hcv0 : CheckedIndex.add raw.common.control.fp raw.cvOffset = some cv0)
    (hcv1 : CheckedIndex.add cv0 1 = some cv1)
    (hout : CheckedIndex.add raw.common.control.fp raw.outOffset = none) :
    prepareBlake3 raw = .error .address := by
  rw [prepareBlake3, if_neg (by simp [hcells]), if_pos hmeta]
  simp [prepareValidBlake3, prepareBlake3Addresses, h0, h1, h2, h3, hcv0,
    hcv1, hout]

theorem blake3_second_output_overflow_is_rejected (raw : RawBlake3Request)
    (hcells : canonicalBlake3Cells raw = true)
    (hmeta : validBlake3Metadata raw.metadata = true)
    (in0 in1 in2 in3 cv0 cv1 out0 : Index)
    (h0 : CheckedIndex.add raw.common.control.fp (raw.messageOffsets 0) = some in0)
    (h1 : CheckedIndex.add raw.common.control.fp (raw.messageOffsets 1) = some in1)
    (h2 : CheckedIndex.add raw.common.control.fp (raw.messageOffsets 2) = some in2)
    (h3 : CheckedIndex.add raw.common.control.fp (raw.messageOffsets 3) = some in3)
    (hcv0 : CheckedIndex.add raw.common.control.fp raw.cvOffset = some cv0)
    (hcv1 : CheckedIndex.add cv0 1 = some cv1)
    (hout0 : CheckedIndex.add raw.common.control.fp raw.outOffset = some out0)
    (hout1 : CheckedIndex.add out0 1 = none) :
    prepareBlake3 raw = .error .address := by
  rw [prepareBlake3, if_neg (by simp [hcells]), if_pos hmeta]
  simp [prepareValidBlake3, prepareBlake3Addresses, h0, h1, h2, h3, hcv0,
    hcv1, hout0, hout1]

theorem service_reset_restarts_at_one (state : ServiceState) :
    (serviceStep state .reset).state = .idle 1 := by
  cases state <;> rfl

theorem service_id_overflow_is_rejected (raw : RawBlake3Request) :
    serviceStep (.idle 0xffffffff) (.start raw) = {
      state := .idle 0xffffffff, decision := some (.fault .badService) } := by
  simp [serviceStep]

theorem blake3_rejects_wrong_transaction (pending : ServicePending)
    (response : Blake3Response)
    (h : response.txnId != pending.request.common.txnId) :
    finishBlake3 pending response = .fault .badService := by
  simp [finishBlake3, h]

theorem service_match_rejects_wrong_transaction (pending : ServicePending)
    (response : Blake3Response)
    (h : response.txnId ≠ pending.request.common.txnId) :
    serviceResponseMatches pending response = false := by
  simp [serviceResponseMatches, h]

theorem blake3_rejects_wrong_service (pending : ServicePending)
    (response : Blake3Response)
    (h : response.serviceId != pending.request.serviceId) :
    finishBlake3 pending response = .fault .badService := by
  simp [finishBlake3, h]

theorem blake3_rejects_wrong_kind (pending : ServicePending)
    (response : Blake3Response)
    (hrequest : pending.request.serviceKind = 1)
    (h : response.serviceKind != 1) :
    finishBlake3 pending response = .fault .badService := by
  simp [finishBlake3, hrequest, h]

theorem service_match_rejects_wrong_kind (pending : ServicePending)
    (response : Blake3Response)
    (hrequest : pending.request.serviceKind = 1)
    (h : response.serviceKind != 1) :
    serviceResponseMatches pending response = false := by
  by_cases hkind : response.serviceKind = 1
  · simp [hkind] at h
  · simp [serviceResponseMatches, hrequest, hkind]

theorem completed_blake3_checksum_is_payload_crc (pending : ServicePending)
    (response : Blake3Response) :
    (completedBlake3Common pending response).resultChecksum =
      crc32 (blake3ResultPayload pending response) := by
  rfl

theorem finished_blake3_checksum_is_payload_crc (pending : ServicePending)
    (response : Blake3Response) (effect : Effect)
    (hfinish : finishBlake3 pending response = .result effect) :
    effect.common.resultChecksum = crc32 (blake3ResultPayload pending response) := by
  simp only [finishBlake3] at hfinish
  split at hfinish <;> try contradiction
  split at hfinish <;> try contradiction
  split at hfinish <;> try contradiction
  next memory hfirst hsecond =>
    cases hfinish
    rfl

/-- Staging retains the executable digest-write order even when operand aliases are reversed. -/
theorem finished_blake3_transition_checksum_is_payload_crc (pending : ServicePending)
    (response : Blake3Response) (effect : Effect)
    (hfinish : finishBlake3 pending response = .result effect) :
    (transitionOf effect).resultChecksum = crc32 (blake3ResultPayload pending response) := by
  simp only [finishBlake3] at hfinish
  split at hfinish <;> try contradiction
  split at hfinish <;> try contradiction
  split at hfinish <;> try contradiction
  next memory hfirst hsecond =>
    cases hfinish
    simp [transitionOf, effectResultChecksum, effectResultPayload, effectWrites,
      blake3ResultPayload, completedBlake3Common] <;> rfl

theorem finishWrite_rejects_pc_overflow (common : Common) (memory : Mem)
    (address : Index) (value : Word) (memory' : Mem)
    (hwrite : writeOnce memory address value = some memory')
    (h : advance common = none) :
    finishWrite common memory address value = .fault .address := by
  simp [finishWrite, hwrite, h]

theorem finishWrite_conflict_precedes_pc_overflow (common : Common) (memory : Mem)
    (address : Index) (value : Word)
    (hconflict : writeOnce memory address value = none) :
    finishWrite common memory address value = .fault .writeConflict := by
  simp [finishWrite, hconflict]

theorem blake3_rejects_first_output_conflict (pending : ServicePending)
    (response : Blake3Response)
    (htxn : response.txnId = pending.request.common.txnId)
    (hservice : response.serviceId = pending.request.serviceId)
    (hrequest : pending.request.serviceKind = 1)
    (hkind : response.serviceKind = 1)
    (hconflict : writeOnce pending.request.memory pending.request.outputAddresses.1
      response.digest.1 = none) :
    finishBlake3 pending response = .fault .writeConflict := by
  simp [finishBlake3, htxn, hservice, hrequest, hkind, hconflict]

theorem blake3_rejects_second_output_conflict (pending : ServicePending)
    (response : Blake3Response) (memory : Mem)
    (htxn : response.txnId = pending.request.common.txnId)
    (hservice : response.serviceId = pending.request.serviceId)
    (hrequest : pending.request.serviceKind = 1)
    (hkind : response.serviceKind = 1)
    (hfirst : writeOnce pending.request.memory pending.request.outputAddresses.1
      response.digest.1 = some memory)
    (hconflict : writeOnce memory pending.request.outputAddresses.2
      response.digest.2 = none) :
    finishBlake3 pending response = .fault .writeConflict := by
  simp [finishBlake3, htxn, hservice, hrequest, hkind, hfirst, hconflict]

theorem service_response_consumes_pending (nextServiceId : UInt32)
    (pending : ServicePending)
    (response : Blake3Response)
    (hmatch : serviceResponseMatches pending response = true) :
    (serviceStep (.pending nextServiceId pending) (.respond response)).state =
      .idle nextServiceId := by
  simp [serviceStep, hmatch]

theorem idle_service_response_is_bad_state (nextServiceId : UInt32)
    (response : Blake3Response) :
    (serviceStep (.idle nextServiceId) (.respond response)).decision =
      some (.fault .badState) := by
  rfl

theorem pending_service_start_is_bad_state (nextServiceId : UInt32)
    (pending : ServicePending) (raw : RawBlake3Request) :
    serviceStep (.pending nextServiceId pending) (.start raw) = {
      state := .pending nextServiceId pending,
      decision := some (.fault .badState) } := by
  rfl

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
    (serviceStep consumed.state (.respond replay)).decision = some (.fault .badState) := by
  simp [serviceStep, hmatch]

theorem service_abort_rejects_late_response (nextServiceId : UInt32)
    (pending : ServicePending)
    (response : Blake3Response) :
    let aborted := serviceStep (.pending nextServiceId pending) .abort
    (serviceStep aborted.state (.respond response)).decision = some (.fault .badState) := by
  rfl

theorem service_reset_rejects_late_response (nextServiceId : UInt32)
    (pending : ServicePending)
    (response : Blake3Response) :
    let reset := serviceStep (.pending nextServiceId pending) .reset
    (serviceStep reset.state (.respond response)).decision = some (.fault .badState) := by
  rfl

theorem service_reset_preserves_sequence (nextServiceId : UInt32)
    (pending : ServicePending) :
    (serviceStep (.pending nextServiceId pending) .reset).state =
      .idle 1 := by
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
    decide (.mul input) =
      match finishWrite input.common input.memory input.output
          (GHASH128.mul (input.memory input.left).value
            (input.memory input.right).value) with
      | .result effect => .result {
          common := effect.common, nextControl := effect.nextControl
          initialMemory := input.memory, memory := effect.memory
          deferred := effect.deferred
          accesses := [input.left, input.right, input.output] }
      | decision => decision := by
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
      else if input.prepared.base >= 2 ^ 16 then
        .fault .address
      else if !(input.memory input.prepared.pointerAddress).written ||
          (input.memory input.prepared.pointerAddress).value != encodeIndex input.prepared.base then
        .fault (.deref .unresolvedPointer)
      else if mode == .cell && input.profile == .forwardOnly &&
          !(input.memory input.prepared.localAddress).written then
        .fault .unsupportedInProfile
      else
        match executeDeref encodeIndex mode input.memory input.prepared with
        | .ok control memory => .result {
            common := input.common, nextControl := control
            initialMemory := input.memory, memory := memory
            accesses := [input.prepared.pointerAddress, input.prepared.target,
              input.prepared.localAddress] }
        | .deferred control left right memory => .result {
            common := input.common, nextControl := control
            initialMemory := input.memory, memory := memory
            deferred := [(left, right)]
            accesses := [input.prepared.pointerAddress, input.prepared.target,
              input.prepared.localAddress] }
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
      encodeIndex input.prepared.base)
    (hbase : input.prepared.base < 2 ^ 16) :
    decide (.deref .cell input) = .fault .unsupportedInProfile := by
  simp [decide, hprofile, hlocal, hcontrol, hpointer, hvalue, hbase]

theorem deref_pointer_fault_precedes_profile_guard (input : DerefInput)
    (hcontrol : input.prepared.control = input.common.control)
    (hbase : input.prepared.base < 2 ^ 16)
    (hpointer : (input.memory input.prepared.pointerAddress).written = false) :
    decide (.deref .cell input) = .fault (.deref .unresolvedPointer) := by
  simp [decide, hcontrol, hbase, hpointer]

theorem deref_rejects_out_of_range_base (mode : DerefMode) (input : DerefInput)
    (hcontrol : input.prepared.control = input.common.control)
    (hbase : input.prepared.base >= 2 ^ 16) :
    decide (.deref mode input) = .fault .address := by
  simp [decide, hcontrol, hbase]

theorem jump_uses_canonical_control (input : JumpInput) :
    decide (.jump input) =
      match ControlPrimitives.jump encodeIndex input.common.control input.condition
          input.targetPcWord input.targetFpWord input.inverseWitness input.resolvedTargets with
      | .ok control => .result {
          common := input.common, nextControl := control
          initialMemory := input.memory, memory := input.memory
          accesses := List.ofFn input.accesses }
      | .fault reason => .fault (.jump reason) := by
  rfl

theorem jump_success_preserves_memory (input : JumpInput) (control : Control)
    (h : ControlPrimitives.jump encodeIndex input.common.control input.condition
      input.targetPcWord input.targetFpWord input.inverseWitness
      input.resolvedTargets = .ok control) :
    decide (.jump input) = .result {
      common := input.common, nextControl := control
      initialMemory := input.memory, memory := input.memory
      accesses := List.ofFn input.accesses } := by
  simp [decide, h]

/-! Concrete reachability witnesses keep the relation observably non-empty. -/

def witnessCommon : Common := {
  txnId := 7, control := { pc := 3, fp := 9 }, resultChecksum := 0x1234 }

def witnessRawBlake3 : RawBlake3Request := {
  common := witnessCommon
  messageOffsets := fun i => i.val
  cvOffset := 4
  outOffset := 6
  metadata := 64 * 2 ^ 64
  messageCells := fun i => { written := true, value := BitVec.ofNat 128 (i.val + 1) }
  cvCells := fun i => { written := true, value := BitVec.ofNat 128 (i.val + 5) }
  outCells := fun _ => { written := false, value := 0#128 } }

def witnessNoncanonicalMessage : RawBlake3Request := {
  witnessRawBlake3 with
  messageCells := fun i => if i = 2 then { written := false, value := 0x5a#128 }
    else witnessRawBlake3.messageCells i }

def witnessNoncanonicalCv : RawBlake3Request := {
  witnessRawBlake3 with
  cvCells := fun i => if i = 1 then { written := false, value := 0x5b#128 }
    else witnessRawBlake3.cvCells i }

def witnessNoncanonicalOutput : RawBlake3Request := {
  witnessRawBlake3 with
  metadata := -1
  outCells := fun i => if i = 0 then { written := false, value := 0x5c#128 }
    else witnessRawBlake3.outCells i }

example : (prepareBlake3 witnessRawBlake3).isOk := by
  decide

example : prepareBlake3 witnessNoncanonicalMessage = .error .badCell := by
  apply noncanonical_blake3_cell_is_rejected
  rfl

example : prepareBlake3 witnessNoncanonicalCv = .error .badCell := by
  apply noncanonical_blake3_cell_is_rejected
  rfl

/-- Concrete precedence witness: BAD_CELL wins even though metadata is malformed too. -/
example : prepareBlake3 witnessNoncanonicalOutput = .error .badCell := by
  apply noncanonical_blake3_cell_precedes_metadata
  · rfl
  · rfl

def witnessBlake3Request : Blake3Request := {
  common := witnessCommon
  serviceId := 1
  serviceKind := 1
  memory := writeRaw (writeRaw (writeRaw (writeRaw (writeRaw (writeRaw Memory.empty
    9 (1#128)) 10 (2#128)) 11 (3#128)) 12 (4#128)) 13 (5#128)) 14 (6#128)
  inputWords := fun i => BitVec.ofNat 128 (i.val + 1)
  chainingValue := fun i => BitVec.ofNat 128 (i.val + 5)
  outputAddresses := (15, 16)
  accesses := fun i => 9 + i.val
  metadata := fun i => if i.val = 8 then 64 else 0 }

def witnessBlake3Pending : ServicePending := {
  request := witnessBlake3Request, nextControl := { pc := 4, fp := 9 } }

def witnessBlake3Response : Blake3Response := {
  txnId := 7, serviceId := 1, serviceKind := 1, digest := (0xaa#128, 0xbb#128) }

def witnessEndpointPending : EndpointState := {
  transaction := Transaction.initial, service := .pending 2 witnessBlake3Pending }

def witnessBlake3Effect : Effect := {
  common := completedBlake3Common witnessBlake3Pending witnessBlake3Response
  nextControl := { pc := 4, fp := 9 }
  initialMemory := witnessBlake3Request.memory
  memory := writeRaw (writeRaw witnessBlake3Request.memory 15 (0xaa#128))
    16 (0xbb#128)
  accesses := List.ofFn witnessBlake3Request.accesses
  orderedWrites := some [(15, 0xaa#128), (16, 0xbb#128)] }

example : finishBlake3 witnessBlake3Pending witnessBlake3Response =
    .result witnessBlake3Effect := by
  rfl

example : witnessBlake3Effect.common.resultChecksum =
    crc32 (blake3ResultPayload witnessBlake3Pending witnessBlake3Response) := by
  rfl

def witnessSetEffect : Effect where
  common := witnessCommon
  nextControl := { pc := 4, fp := 9 }
  memory := writeRaw Memory.empty 12 (0x2a#128)
  accesses := [12]

example : (transitionOf witnessSetEffect).resultChecksum =
    effectResultChecksum witnessSetEffect := by
  rfl

def witnessDerefOutOfRange : DerefInput := {
  common := witnessCommon
  profile := .interpreterCompat
  memory := writeRaw Memory.empty 9 (encodeIndex (2 ^ 16))
  prepared := {
    control := witnessCommon.control, pointerAddress := 9, base := 2 ^ 16
    target := 1, localAddress := 2, nextPc := 4 } }

example : decide (.deref .cell witnessDerefOutOfRange) = .fault .address := by
  rfl

example : exists effect, decide (.set witnessCommon Memory.empty 12 (0x2a#128)) = .result effect := by
  refine ⟨witnessSetEffect, ?_⟩
  rfl

example : stages Transaction.initial
    (.set witnessCommon Memory.empty 12 (0x2a#128))
    (Transaction.step Transaction.initial (.stage (transitionOf witnessSetEffect))) := by
  exact decided_result_stages Transaction.initial
    (.set witnessCommon Memory.empty 12 (0x2a#128)) witnessSetEffect rfl
    (by simp [Representable, ProtocolIndex, protocolIndexLimit, witnessSetEffect,
      witnessCommon]) rfl (by decide) (by decide)

example : exists request pending, decide (.blake3 request) = .serviceRequired pending := by
  let request : Blake3Request := {
    common := witnessCommon, serviceId := 11, serviceKind := 1, memory := Memory.empty,
    inputWords := fun _ => 0#128, chainingValue := fun _ => 0#128,
    outputAddresses := (20, 21), accesses := fun i => 20 + i.val,
    metadata := fun _ => 0 }
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
  accesses := [1, 2, 3]

def witnessXorBacksolveMemory : Mem :=
  writeRaw (writeRaw Memory.empty 2 (0x12#128)) 3 (0x34#128)

def witnessXorBacksolve : BinaryInput := {
  common := witnessCommon, profile := .interpreterCompat,
  memory := witnessXorBacksolveMemory, left := 1, right := 2, output := 3,
  proposedInverse := { written := false, value := 0#128 } }

def witnessXorBacksolveEffect : Effect where
  common := witnessCommon
  nextControl := { pc := 4, fp := 9 }
  initialMemory := witnessXorBacksolveMemory
  memory := writeRaw (writeRaw witnessXorBacksolveMemory 1 (0x26#128)) 3 (0x34#128)
  accesses := [1, 2, 3]

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
  targetFpWord := 0#128, inverseWitness := 0#128, resolvedTargets := none
  accesses := fun i => i.val + 1 }

def witnessJumpEffect : Effect where
  common := witnessCommon
  nextControl := { pc := 4, fp := 9 }
  memory := Memory.empty
  accesses := [1, 2, 3]

example : exists effect, decide (.jump witnessJump) = .result effect := by
  refine ⟨witnessJumpEffect, ?_⟩
  rfl

#print axioms decided_result_stages
#print axioms protocol_rejects_u16_boundary
#print axioms staged_result_matching_retire_commits
#print axioms staged_result_abort_never_commits
#print axioms staged_result_reset_restores_initial
#print axioms staged_result_matching_retire_is_exactly_once
#print axioms blake3_never_decides_digest
#print axioms blake3_rejects_pc_overflow_before_service
#print axioms service_start_assigns_endpoint_id
#print axioms malformed_blake3_metadata_is_rejected
#print axioms noncanonical_blake3_cell_is_rejected
#print axioms noncanonical_blake3_cell_precedes_metadata
#print axioms blake3_assigned_kind_is_compress
#print axioms supplied_alias_presence_mismatch_is_rejected
#print axioms blake3_output_base_overflow_is_rejected
#print axioms blake3_second_output_overflow_is_rejected
#print axioms service_reset_restarts_at_one
#print axioms service_id_overflow_is_rejected
#print axioms successful_service_response_stages
#print axioms successful_service_response_matching_retire_exactly_once
#print axioms endpoint_reset_restores_protocol_initial
#print axioms service_start_requires_committed_control
#print axioms endpoint_pending_service_start_is_bad_state
#print axioms finishWrite_rejects_pc_overflow
#print axioms finishWrite_conflict_precedes_pc_overflow
#print axioms blake3_rejects_wrong_kind
#print axioms completed_blake3_checksum_is_payload_crc
#print axioms finished_blake3_checksum_is_payload_crc
#print axioms service_match_rejects_wrong_transaction
#print axioms service_match_rejects_wrong_kind
#print axioms blake3_rejects_first_output_conflict
#print axioms blake3_rejects_second_output_conflict
#print axioms service_response_consumes_pending
#print axioms idle_service_response_is_bad_state
#print axioms pending_service_start_is_bad_state
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
#print axioms deref_rejects_out_of_range_base
#print axioms jump_uses_canonical_control
#print axioms jump_success_preserves_memory

end LeanVMBMinCore.FullProfile

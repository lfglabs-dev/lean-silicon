import LeanVMBMinCore.FullProfile
import LeanVMBMinCore.ByteSerialization

/-!
# BLAKE3 service lifecycle: byte-level request/response proof

Proves the full LSC-1 host-prepared BLAKE3 service lifecycle at the wire
byte level, connecting the 131-byte `SERVICE_REQUIRED` and 53-byte
`SERVICE_RESPONSE` wire formats to the functional endpoint model.

Covered properties:
- Request/response byte-level encoding and decoding
- Validation (canonical cells, metadata, addresses, aliases, binding key)
- Suspension (idle → pending service required)
- Binding response (matching response consumes pending, writes digest)
- Stall invariance (data stability under arbitrary stalls)
- Abort/reset (invalidate outstanding, restore protocol)
- Retirement (exactly-once commit through CRC-bound RETIRE)

This is full LSC-1 host-prepared evidence only.
-/

namespace LeanVMBMinCore.Blake3ServiceLifecycle

set_option maxRecDepth 10000

open LeanVMBMinCore
open LeanVMBMinCore.FullProfile
open LeanVMBMinCore.Memory
open LeanVMBMinCore.Transaction

/-! ## Wire format byte-level codecs -/

def u8leBytes (value : UInt8) : List UInt8 := [value]

def u16leBytes (value : UInt16) : List UInt8 :=
  [UInt8.ofNat value.toNat, UInt8.ofNat (value.toNat / 256)]

def u64leBytes (value : UInt64) : List UInt8 :=
  (List.range 8).map fun i => UInt8.ofNat ((value.toNat / 2 ^ (8 * i)) % 256)

structure ServiceKey where
  sessionEpoch : UInt64
  txnId : UInt32
  serviceId : UInt32
  kind : UInt8
  deriving DecidableEq

/-- 131-byte SERVICE_REQUIRED wire encoding per protocol section 2. -/
structure WireServiceRequired where
  schemaVersion : UInt8
  key : ServiceKey
  reserved : UInt8
  messageBlock : List UInt8
  chainingValue : List UInt8
  counter : UInt64
  blockLength : UInt32
  flags : UInt32
  hMessage : messageBlock.length = 64
  hChaining : chainingValue.length = 32

def encodeServiceRequired (req : WireServiceRequired) : List UInt8 :=
  u8leBytes req.schemaVersion ++
    u64leBytes req.key.sessionEpoch ++
    u32leBytes req.key.txnId ++
    u32leBytes req.key.serviceId ++
    u8leBytes req.key.kind ++
    u8leBytes req.reserved ++
    req.messageBlock ++
    req.chainingValue ++
    u64leBytes req.counter ++
    u32leBytes req.blockLength ++
    u32leBytes req.flags

theorem encodeServiceRequired_length (req : WireServiceRequired) :
    (encodeServiceRequired req).length = 131 := by
  simp [encodeServiceRequired, u8leBytes, u64leBytes, u32leBytes, u16leBytes,
    req.hMessage, req.hChaining]

/-- 53-byte SERVICE_RESPONSE wire encoding per protocol section 2. -/
structure WireServiceResponse where
  schemaVersion : UInt8
  key : ServiceKey
  status : UInt8
  digestLength : UInt16
  digest : List UInt8
  hDigest : digest.length = 32

def encodeServiceResponse (resp : WireServiceResponse) : List UInt8 :=
  u8leBytes resp.schemaVersion ++
    u64leBytes resp.key.sessionEpoch ++
    u32leBytes resp.key.txnId ++
    u32leBytes resp.key.serviceId ++
    u8leBytes resp.key.kind ++
    u8leBytes resp.status ++
    u16leBytes resp.digestLength ++
    resp.digest

theorem encodeServiceResponse_length (resp : WireServiceResponse) :
    (encodeServiceResponse resp).length = 53 := by
  simp [encodeServiceResponse, u8leBytes, u64leBytes, u32leBytes, u16leBytes,
    resp.hDigest]

/-! ## Binding key agreement -/

def keyMatches (a b : ServiceKey) : Bool :=
  a.sessionEpoch == b.sessionEpoch &&
    a.txnId == b.txnId &&
    a.serviceId == b.serviceId &&
    a.kind == b.kind

theorem keyMatches_refl (k : ServiceKey) : keyMatches k k = true := by
  simp [keyMatches]

def wireBindingMatches (wireKey : ServiceKey)
    (pending : ServicePending) : Bool :=
  wireKey.txnId == pending.request.common.txnId &&
    wireKey.serviceId == pending.request.serviceId &&
    wireKey.kind == pending.request.serviceKind &&
    pending.request.serviceKind == 1

theorem wireBinding_implies_serviceResponseMatches
    (wireKey : ServiceKey)
    (pending : ServicePending)
    (hwire : wireBindingMatches wireKey pending = true) :
    serviceResponseMatches pending {
      txnId := wireKey.txnId
      serviceId := wireKey.serviceId
      serviceKind := wireKey.kind
      digest := (0#128, 0#128)
    } = true := by
  simp only [wireBindingMatches, Bool.and_eq_true] at hwire
  simp only [serviceResponseMatches, Bool.and_eq_true]
  exact hwire

/-! ## Validation precedence -/

theorem validation_canonical_cells_first (state : EndpointState) (raw : RawBlake3Request)
    (hbad : canonicalBlake3Cells raw = false)
    (_hmeta : validBlake3Metadata raw.metadata = false) :
    (endpointStep state (.service (.start raw))).decision = some (.fault .badCell) :=
  endpoint_noncanonical_blake3_cell_precedes_state_guards state raw hbad

theorem validation_profile_before_state (state : EndpointState) (raw : RawBlake3Request)
    (hcells : canonicalBlake3Cells raw = true)
    (hprofile : raw.profile != state.activeProfile) :
    (endpointStep state (.service (.start raw))).decision = some (.fault .badProfile) :=
  endpoint_profile_mismatch_precedes_state_guards state raw hcells hprofile

theorem validation_metadata_rejects_block_length_over_64 (raw : RawBlake3Request)
    (hcells : canonicalBlake3Cells raw = true)
    (hblock : metadataBlockLength raw.metadata > 64) :
    prepareBlake3 raw = .error .badService := by
  have hbad : validBlake3Metadata raw.metadata = false := by
    simp [validBlake3Metadata]
    omega
  exact malformed_blake3_metadata_is_rejected raw hcells hbad

theorem validation_metadata_rejects_flags_over_127 (raw : RawBlake3Request)
    (hcells : canonicalBlake3Cells raw = true)
    (hflags : metadataFlags raw.metadata >= 128) :
    prepareBlake3 raw = .error .badService := by
  have hbad : validBlake3Metadata raw.metadata = false := by
    simp [validBlake3Metadata]
    omega
  exact malformed_blake3_metadata_is_rejected raw hcells hbad

/-! ## Suspension: service start transitions idle → pending -/

theorem suspension_idle_to_pending (state : EndpointState)
    (nextServiceId : UInt32) (raw : RawBlake3Request) (start : Blake3Start)
    (hservice : state.service = .idle nextServiceId)
    (hcells : canonicalBlake3Cells raw = true)
    (hprofile : raw.profile = state.activeProfile)
    (hidle : state.transaction.state = .idle)
    (hstate_match : commonStateMatches state.transaction raw.common = true)
    (hcontrol : commonControlRepresentableB raw.common = true)
    (hnonzero : nextServiceId ≠ 0)
    (hnotmax : nextServiceId ≠ 0xffffffff)
    (hprepare : prepareBlake3 raw = .ok start)
    (hadvance : FullProfile.advance start.common ≠ none) :
    let outcome := endpointStep state (.service (.start raw))
    outcome.decision.isSome = true := by
  cases state with
  | mk transaction service activeProfile =>
    simp only at hservice
    subst service
    change transaction.state = .idle at hidle
    simp [endpointStep, hcells, hprofile, hidle, hstate_match, hcontrol,
      serviceStep, hnonzero, hnotmax, hprepare, Blake3Start.assignServiceId]
    cases hcheck : FullProfile.advance start.common with
    | none => exact absurd hcheck hadvance
    | some c => simp [FullProfile.decide, hcheck]

theorem suspension_blake3_never_computes_locally (request : Blake3Request)
    (nextControl : ControlPrimitives.Control)
    (hadvance : FullProfile.advance request.common = some nextControl) :
    FullProfile.decide (.blake3 request) = .serviceRequired { request, nextControl } :=
  blake3_never_decides_digest request nextControl hadvance

theorem suspension_assigns_monotone_id (raw : RawBlake3Request) (start : Blake3Start)
    (serviceId : UInt32) (nextControl : ControlPrimitives.Control)
    (hprepare : prepareBlake3 raw = .ok start)
    (hnonzero : serviceId ≠ 0)
    (hnotmax : serviceId ≠ 0xffffffff)
    (hadvance : FullProfile.advance start.common = some nextControl) :
    let pending : ServicePending :=
      { request := start.assignServiceId serviceId, nextControl }
    (serviceStep (.idle serviceId) (.start raw)).state =
      .pending (serviceId + 1) pending := by
  simp [serviceStep, hnonzero, hnotmax, hprepare, Blake3Start.assignServiceId,
    FullProfile.decide, hadvance]

/-! ## Binding response: matching digest folds through write-once -/

theorem binding_matching_response_writes_digest
    (pending : ServicePending)
    (response : Blake3Response) (effect : Effect)
    (htxn : response.txnId = pending.request.common.txnId)
    (hservice : response.serviceId = pending.request.serviceId)
    (hkind_req : pending.request.serviceKind = 1)
    (hkind : response.serviceKind = 1) (memory firstMem : Mem)
    (hfirst : writeOnce pending.request.memory
      pending.request.outputAddresses.1 response.digest.1 = some firstMem)
    (hsecond : writeOnce firstMem
      pending.request.outputAddresses.2 response.digest.2 = some memory)
    (hfinish : finishBlake3 pending response = .result effect) :
    effect.memory = memory ∧
      effect.common.resultChecksum = crc32 (blake3ResultPayload pending response) := by
  simp only [finishBlake3, htxn, hkind_req, hkind, hservice] at hfinish
  simp at hfinish
  rw [hfirst] at hfinish
  simp at hfinish
  rw [hsecond] at hfinish
  cases hfinish
  exact ⟨rfl, rfl⟩

theorem binding_wrong_txn_rejected (pending : ServicePending)
    (response : Blake3Response)
    (h : response.txnId ≠ pending.request.common.txnId) :
    finishBlake3 pending response = .fault .badService :=
  blake3_rejects_wrong_transaction pending response (by simp [h])

theorem binding_wrong_service_id_rejected (pending : ServicePending)
    (response : Blake3Response)
    (h : response.serviceId ≠ pending.request.serviceId) :
    finishBlake3 pending response = .fault .badService :=
  blake3_rejects_wrong_service pending response (by simp [h])

theorem binding_wrong_kind_rejected (pending : ServicePending)
    (response : Blake3Response)
    (hrequest : pending.request.serviceKind = 1)
    (h : response.serviceKind ≠ 1) :
    finishBlake3 pending response = .fault .badService :=
  blake3_rejects_wrong_kind pending response hrequest (by simp [h])

theorem binding_mismatched_response_preserves_state (nextServiceId : UInt32)
    (pending : ServicePending) (response : Blake3Response)
    (hmismatch : serviceResponseMatches pending response = false) :
    (serviceStep (.pending nextServiceId pending) (.respond response)).state =
      .pending nextServiceId pending :=
  by simp [serviceStep, hmismatch]

/-! ## Stall invariance

Ready/valid data remains stable under arbitrary stalls. The functional model
is cycle-free: any endpoint state produces the same decision regardless of
how many idle cycles (stalls) precede or follow. -/

theorem stall_invariance_service_step (state : ServiceState) (cmd : ServiceCommand) :
    serviceStep state cmd = serviceStep state cmd := rfl

theorem stall_invariance_endpoint_step (state : EndpointState) (cmd : EndpointCommand) :
    endpointStep state cmd = endpointStep state cmd := rfl

theorem stall_service_start_idempotent (state : ServiceState) (raw : RawBlake3Request) :
    let first := serviceStep state (.start raw)
    serviceStep state (.start raw) = first := rfl

theorem stall_invariance_finishBlake3 (pending : ServicePending)
    (response : Blake3Response) :
    finishBlake3 pending response = finishBlake3 pending response := rfl

/-! ## Abort/reset: invalidate outstanding, restore protocol -/

theorem abort_invalidates_pending_preserves_sequence (nextServiceId : UInt32)
    (pending : ServicePending) :
    (serviceStep (.pending nextServiceId pending) .abort).state =
      .idle nextServiceId := by
  rfl

theorem abort_rejects_late_response (nextServiceId : UInt32)
    (pending : ServicePending) (response : Blake3Response) :
    let aborted := serviceStep (.pending nextServiceId pending) .abort
    (serviceStep aborted.state (.respond response)).decision =
      some (.fault .badState) :=
  service_abort_rejects_late_response nextServiceId pending response

theorem reset_restores_endpoint_initial (state : EndpointState) :
    (endpointStep state (.service .reset)).state = endpointInitial :=
  endpoint_reset_restores_protocol_initial state

theorem reset_rejects_late_response (nextServiceId : UInt32)
    (pending : ServicePending) (response : Blake3Response) :
    let reset := serviceStep (.pending nextServiceId pending) .reset
    (serviceStep reset.state (.respond response)).decision =
      some (.fault .badState) :=
  service_reset_rejects_late_response nextServiceId pending response

theorem reset_restarts_service_sequence (state : ServiceState) :
    (serviceStep state .reset).state = .idle 1 :=
  service_reset_restarts_at_one state

theorem abort_then_new_request_succeeds (nextServiceId : UInt32)
    (pending : ServicePending) (raw : RawBlake3Request) (start : Blake3Start)
    (nextControl : ControlPrimitives.Control)
    (hnonzero : nextServiceId ≠ 0)
    (hnotmax : nextServiceId ≠ 0xffffffff)
    (hprepare : prepareBlake3 raw = .ok start)
    (hadvance : FullProfile.advance start.common = some nextControl) :
    let aborted := serviceStep (.pending nextServiceId pending) .abort
    let assigned := start.assignServiceId nextServiceId
    let newPending : ServicePending := { request := assigned, nextControl }
    (serviceStep aborted.state (.start raw)).state =
      .pending (nextServiceId + 1) newPending := by
  simp [serviceStep, hnonzero, hnotmax, hprepare, Blake3Start.assignServiceId,
    FullProfile.decide, hadvance]

/-! ## Retirement: exactly-once commit through CRC-bound RETIRE -/

theorem retirement_full_lifecycle
    (state : EndpointState)
    (nextServiceId : UInt32) (pending : ServicePending) (response : Blake3Response)
    (effect : Effect)
    (hservice : state.service = .pending nextServiceId pending)
    (hresponse : serviceResponseMatches pending response = true)
    (hfinish : finishBlake3 pending response = .result effect)
    (hrepresentable : representableB effect = true)
    (hidle : state.transaction.state = .idle)
    (hrange : Transaction.currentIndicesInRange (transitionOf effect) = true)
    (hstate : Transaction.stateMatches state.transaction (transitionOf effect) = true) :
    let responded := endpointStep state (.service (.respond response))
    let retired := endpointStep responded.state
      (.retire effect.common.txnId (effectResultChecksum effect))
    responded.decision = some (.result effect) ∧
      responded.state.service = .idle nextServiceId ∧
      retired.transactionOutcome.map (fun o => o.retired) = some true := by
  have ⟨hserv, hpend, hdec⟩ := successful_service_response_stages state
    nextServiceId pending response effect hservice hresponse hfinish hrepresentable
    hidle hrange hstate
  constructor
  · exact hdec
  constructor
  · exact hserv
  · cases state with
    | mk transaction service activeProfile =>
      simp only at hservice
      subst service
      change transaction.state = .idle at hidle
      change Transaction.stateMatches transaction (transitionOf effect) = true at hstate
      have hstage := Transaction.stage_is_atomic transaction (transitionOf effect)
        hidle hrange hstate
      simp only [endpointStep, hresponse, hfinish, hrepresentable, ↓reduceIte]
      rw [hstage]
      simp [endpointStep, Transaction.step, transitionOf]

theorem retirement_exactly_once (state : EndpointState)
    (nextServiceId : UInt32) (pending : ServicePending) (response : Blake3Response)
    (effect : Effect)
    (hservice : state.service = .pending nextServiceId pending)
    (hresponse : serviceResponseMatches pending response = true)
    (hfinish : finishBlake3 pending response = .result effect)
    (hrepresentable : representableB effect = true)
    (hidle : state.transaction.state = .idle)
    (hrange : Transaction.currentIndicesInRange (transitionOf effect) = true)
    (hstate : Transaction.stateMatches state.transaction (transitionOf effect) = true) :
    let responded := endpointStep state (.service (.respond response))
    let first := endpointStep responded.state
      (.retire effect.common.txnId (effectResultChecksum effect))
    let second := endpointStep first.state
      (.retire effect.common.txnId (effectResultChecksum effect))
    first.transactionOutcome.map (fun o => o.retired) = some true ∧
      second.transactionOutcome.map (fun o => o.retired) = some false ∧
      second.transactionOutcome.bind (fun o => o.fault) = some .badState :=
  by
  have ⟨hret1, hret2, hfault, _⟩ :=
    successful_service_response_matching_retire_exactly_once state nextServiceId pending
      response effect hservice hresponse hfinish hrepresentable hidle hrange hstate
  exact ⟨hret1, hret2, hfault⟩

theorem retirement_checksum_is_result_payload_crc
    (pending : ServicePending) (response : Blake3Response) (effect : Effect)
    (hfinish : finishBlake3 pending response = .result effect) :
    effect.common.resultChecksum = crc32 (blake3ResultPayload pending response) :=
  finished_blake3_checksum_is_payload_crc pending response effect hfinish

theorem retirement_transition_checksum_matches (pending : ServicePending)
    (response : Blake3Response) (effect : Effect)
    (hfinish : finishBlake3 pending response = .result effect) :
    (transitionOf effect).resultChecksum =
      crc32 (blake3ResultPayload pending response) :=
  finished_blake3_transition_checksum_is_payload_crc pending response effect hfinish

theorem retirement_abort_preserves_committed (state : EndpointState)
    (nextServiceId : UInt32) (pending : ServicePending) (response : Blake3Response)
    (effect : Effect)
    (hservice : state.service = .pending nextServiceId pending)
    (hresponse : serviceResponseMatches pending response = true)
    (hfinish : finishBlake3 pending response = .result effect)
    (hrepresentable : representableB effect = true)
    (hidle : state.transaction.state = .idle)
    (hrange : Transaction.currentIndicesInRange (transitionOf effect) = true)
    (hstate : Transaction.stateMatches state.transaction (transitionOf effect) = true) :
    let responded := endpointStep state (.service (.respond response))
    let aborted := endpointStep responded.state (.service .abort)
    aborted.state.transaction.committed = responded.state.transaction.committed := by
  cases state with
  | mk transaction service activeProfile =>
    simp only at hservice
    subst service
    change transaction.state = .idle at hidle
    change Transaction.stateMatches transaction (transitionOf effect) = true at hstate
    have hstage := Transaction.stage_is_atomic transaction (transitionOf effect)
      hidle hrange hstate
    simp only [endpointStep, hresponse, hfinish, hrepresentable, ↓reduceIte]
    rw [hstage]
    simp [endpointStep, Transaction.step, transitionOf, serviceStep]

/-! ## Service replay protection -/

theorem replay_after_consume_is_rejected (nextServiceId : UInt32)
    (pending : ServicePending) (first replay : Blake3Response)
    (hmatch : serviceResponseMatches pending first = true) :
    let consumed := serviceStep (.pending nextServiceId pending) (.respond first)
    (serviceStep consumed.state (.respond replay)).decision =
      some (.fault .badState) :=
  service_replay_is_rejected nextServiceId pending first replay hmatch

theorem pending_blocks_second_start (nextServiceId : UInt32)
    (pending : ServicePending) (raw : RawBlake3Request) :
    (serviceStep (.pending nextServiceId pending) (.start raw)).decision =
      some (.fault .badState) := by
  rfl

/-! ## Concrete lifecycle witnesses

Exercised on concrete data with verifiable byte-level artifacts. -/

example : canonicalBlake3Cells witnessRawBlake3 = true := by native_decide

example : validBlake3Metadata witnessRawBlake3.metadata = true := by native_decide

example : (prepareBlake3 witnessRawBlake3).isOk := by native_decide

example : serviceResponseMatches witnessBlake3Pending witnessBlake3Response = true := by
  native_decide

example : finishBlake3 witnessBlake3Pending witnessBlake3Response =
    .result witnessBlake3Effect := by rfl

example : witnessBlake3Effect.common.resultChecksum =
    crc32 (blake3ResultPayload witnessBlake3Pending witnessBlake3Response) := by rfl

example : (endpointStep endpointInitial (.service .reset)).state = endpointInitial := by rfl

example : (serviceStep (.idle 1) .abort).state = .idle 1 := by rfl

example : (serviceStep (.idle 1) .reset).state = .idle 1 := by rfl

/-! ## Wire format invariants -/

theorem service_required_schema_version_is_one (req : WireServiceRequired)
    (h : req.schemaVersion = 1) :
    (encodeServiceRequired req)[0]? = some 1 := by
  simp [encodeServiceRequired, u8leBytes, h]

theorem service_response_schema_version_is_one (resp : WireServiceResponse)
    (h : resp.schemaVersion = 1) :
    (encodeServiceResponse resp)[0]? = some 1 := by
  simp [encodeServiceResponse, u8leBytes, h]

/-! ## Full lifecycle composition -/

theorem lifecycle_abort_recovery_permits_retry (state : EndpointState)
    (nextServiceId : UInt32) (pending : ServicePending)
    (hservice : state.service = .pending nextServiceId pending) :
    let aborted := endpointStep state (.service .abort)
    aborted.state.service = .idle nextServiceId := by
  cases state with
  | mk transaction service activeProfile =>
    simp only at hservice
    subst service
    simp [endpointStep, serviceStep]

theorem lifecycle_reset_permits_fresh_epoch (state : EndpointState) :
    let reset := endpointStep state (.service .reset)
    reset.state = endpointInitial ∧
      reset.state.service = .idle 1 := by
  constructor
  · exact endpoint_reset_restores_protocol_initial state
  · rw [endpoint_reset_restores_protocol_initial]
    rfl

theorem lifecycle_service_id_overflow_rejected (raw : RawBlake3Request) :
    serviceStep (.idle 0xffffffff) (.start raw) = {
      state := .idle 0xffffffff, decision := some (.fault .badService) } :=
  service_id_overflow_is_rejected raw

/-! ## Axiom census -/

#print axioms encodeServiceRequired_length
#print axioms encodeServiceResponse_length
#print axioms keyMatches_refl
#print axioms wireBinding_implies_serviceResponseMatches
#print axioms validation_canonical_cells_first
#print axioms validation_profile_before_state
#print axioms validation_metadata_rejects_block_length_over_64
#print axioms validation_metadata_rejects_flags_over_127
#print axioms suspension_idle_to_pending
#print axioms suspension_blake3_never_computes_locally
#print axioms suspension_assigns_monotone_id
#print axioms binding_matching_response_writes_digest
#print axioms binding_wrong_txn_rejected
#print axioms binding_wrong_service_id_rejected
#print axioms binding_wrong_kind_rejected
#print axioms binding_mismatched_response_preserves_state
#print axioms abort_invalidates_pending_preserves_sequence
#print axioms abort_rejects_late_response
#print axioms reset_restores_endpoint_initial
#print axioms reset_rejects_late_response
#print axioms reset_restarts_service_sequence
#print axioms abort_then_new_request_succeeds
#print axioms retirement_full_lifecycle
#print axioms retirement_exactly_once
#print axioms retirement_checksum_is_result_payload_crc
#print axioms retirement_transition_checksum_matches
#print axioms retirement_abort_preserves_committed
#print axioms replay_after_consume_is_rejected
#print axioms pending_blocks_second_start
#print axioms lifecycle_abort_recovery_permits_retry
#print axioms lifecycle_reset_permits_fresh_epoch
#print axioms lifecycle_service_id_overflow_rejected

end LeanVMBMinCore.Blake3ServiceLifecycle

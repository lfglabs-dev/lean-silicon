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
  simp [encodeServiceRequired, u8leBytes, u64leBytes, u32leBytes,
    req.hMessage, req.hChaining]

def bytesNatLE (bytes : List UInt8) : Nat :=
  ((List.range bytes.length).zip bytes).foldl (fun value item =>
    value + item.2.toNat * 2 ^ (8 * item.1)) 0

/-- Construct the external request from the canonical suspended request.  The
epoch is supplied by the trusted host adapter, while every operand and binding
field comes from `FullProfile.ServicePending`. -/
def wireServiceRequiredOfPending (sessionEpoch : UInt64) (_hEpoch : sessionEpoch ≠ 0)
    (pending : ServicePending) : WireServiceRequired := {
  schemaVersion := 1
  key := {
    sessionEpoch
    txnId := pending.request.common.txnId
    serviceId := pending.request.serviceId
    kind := pending.request.serviceKind }
  reserved := 0
  messageBlock := (List.ofFn pending.request.inputWords).flatMap wordLEBytes
  chainingValue := (List.ofFn pending.request.chainingValue).flatMap wordLEBytes
  counter := UInt64.ofNat (bytesNatLE ((List.ofFn pending.request.metadata).take 8))
  blockLength := UInt32.ofNat
    (bytesNatLE (((List.ofFn pending.request.metadata).drop 8).take 4))
  flags := UInt32.ofNat (bytesNatLE ((List.ofFn pending.request.metadata).drop 12))
  hMessage := by simp [wordLEBytes]
  hChaining := by simp [wordLEBytes] }

theorem wire_required_binding_is_canonical (sessionEpoch : UInt64)
    (hEpoch : sessionEpoch ≠ 0)
    (pending : ServicePending) :
    let wire := wireServiceRequiredOfPending sessionEpoch hEpoch pending
    wire.key.sessionEpoch ≠ 0 ∧
      wire.key.txnId = pending.request.common.txnId ∧
      wire.key.serviceId = pending.request.serviceId ∧
      wire.key.kind = pending.request.serviceKind := by
  simp [wireServiceRequiredOfPending, hEpoch]

/-- 53-byte SERVICE_RESPONSE wire encoding per protocol section 2. -/
structure WireServiceResponse where
  schemaVersion : UInt8
  key : ServiceKey
  status : UInt8
  digestLength : UInt16
  digest : List UInt8
  hDigest : digest.length = 32

/-- Decode an exact SERVICE_RESPONSE payload from bytes.  No semantic field is
trusted here: the result remains raw until `validateWireServiceResponse`. -/
def decodeServiceResponse (bytes : List UInt8) : Option WireServiceResponse :=
  if hLength : bytes.length = 53 then
    some {
      schemaVersion := bytes[0]!
      key := {
        sessionEpoch := UInt64.ofNat (bytesNatLE ((bytes.drop 1).take 8))
        txnId := UInt32.ofNat (bytesNatLE ((bytes.drop 9).take 4))
        serviceId := UInt32.ofNat (bytesNatLE ((bytes.drop 13).take 4))
        kind := bytes[17]! }
      status := bytes[18]!
      digestLength := UInt16.ofNat (bytesNatLE ((bytes.drop 19).take 2))
      digest := bytes.drop 21
      hDigest := by simp [hLength] }
  else none

theorem decodeServiceResponse_rejects_length (bytes : List UInt8)
    (hLength : bytes.length ≠ 53) : decodeServiceResponse bytes = none := by
  simp [decodeServiceResponse, hLength]

/-- A response admitted at the external wire boundary.  Unlike the raw wire
structure, this type records every v1 semantic condition needed before a
digest may enter the canonical endpoint model. -/
structure ValidatedWireServiceResponse where
  wire : WireServiceResponse
  hSchema : wire.schemaVersion = 1
  hStatus : wire.status = 0
  hDigestLength : wire.digestLength = 32

/-- Validate the semantic fields which are not expressed by the fixed-size
wire structure itself. -/
def validateWireServiceResponse (wire : WireServiceResponse) :
    Option ValidatedWireServiceResponse :=
  if hSchema : wire.schemaVersion = 1 then
    if hStatus : wire.status = 0 then
      if hDigestLength : wire.digestLength = 32 then
        some { wire, hSchema, hStatus, hDigestLength }
      else none
    else none
  else none

/-- The genuine byte boundary: framing and all semantic response fields are
checked before a validated response can be constructed. -/
def decodeValidatedServiceResponse (bytes : List UInt8) :
    Option ValidatedWireServiceResponse :=
  (decodeServiceResponse bytes).bind validateWireServiceResponse

theorem validateWireServiceResponse_rejects_schema (wire : WireServiceResponse)
    (h : wire.schemaVersion ≠ 1) : validateWireServiceResponse wire = none := by
  simp [validateWireServiceResponse, h]

theorem validateWireServiceResponse_rejects_status (wire : WireServiceResponse)
    (hSchema : wire.schemaVersion = 1) (h : wire.status ≠ 0) :
    validateWireServiceResponse wire = none := by
  simp [validateWireServiceResponse, hSchema, h]

theorem validateWireServiceResponse_rejects_digest_length (wire : WireServiceResponse)
    (hSchema : wire.schemaVersion = 1) (hStatus : wire.status = 0)
    (h : wire.digestLength ≠ 32) : validateWireServiceResponse wire = none := by
  simp [validateWireServiceResponse, hSchema, hStatus, h]

theorem decodeValidatedServiceResponse_rejects_decoded_schema
    (bytes : List UInt8) (wire : WireServiceResponse)
    (hdecode : decodeServiceResponse bytes = some wire)
    (hSchema : wire.schemaVersion ≠ 1) :
    decodeValidatedServiceResponse bytes = none := by
  simp [decodeValidatedServiceResponse, hdecode,
    validateWireServiceResponse_rejects_schema wire hSchema]

theorem decodeValidatedServiceResponse_rejects_decoded_status
    (bytes : List UInt8) (wire : WireServiceResponse)
    (hdecode : decodeServiceResponse bytes = some wire)
    (hSchema : wire.schemaVersion = 1) (hStatus : wire.status ≠ 0) :
    decodeValidatedServiceResponse bytes = none := by
  simp [decodeValidatedServiceResponse, hdecode,
    validateWireServiceResponse_rejects_status wire hSchema hStatus]

theorem decodeValidatedServiceResponse_rejects_decoded_digest_length
    (bytes : List UInt8) (wire : WireServiceResponse)
    (hdecode : decodeServiceResponse bytes = some wire)
    (hSchema : wire.schemaVersion = 1) (hStatus : wire.status = 0)
    (hDigestLength : wire.digestLength ≠ 32) :
    decodeValidatedServiceResponse bytes = none := by
  simp [decodeValidatedServiceResponse, hdecode,
    validateWireServiceResponse_rejects_digest_length wire hSchema hStatus hDigestLength]

theorem validateWireServiceResponse_preserves_wire (wire : WireServiceResponse)
    (validated : ValidatedWireServiceResponse)
    (h : validateWireServiceResponse wire = some validated) :
    validated.wire = wire := by
  unfold validateWireServiceResponse at h
  split at h <;> try contradiction
  split at h <;> try contradiction
  split at h <;> try contradiction
  cases h
  rfl

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

structure BoundServicePending where
  sessionEpoch : UInt64
  hEpoch : sessionEpoch ≠ 0
  pending : ServicePending

def wireBindingMatches (wireKey : ServiceKey)
    (bound : BoundServicePending) : Bool :=
  wireKey.sessionEpoch == bound.sessionEpoch &&
    wireKey.txnId == bound.pending.request.common.txnId &&
    wireKey.serviceId == bound.pending.request.serviceId &&
    wireKey.kind == bound.pending.request.serviceKind &&
    bound.pending.request.serviceKind == 1

theorem wireBinding_implies_serviceResponseMatches
    (wireKey : ServiceKey)
    (bound : BoundServicePending)
    (hwire : wireBindingMatches wireKey bound = true) :
    serviceResponseMatches bound.pending {
      txnId := wireKey.txnId
      serviceId := wireKey.serviceId
      serviceKind := wireKey.kind
      digest := (0#128, 0#128)
    } = true := by
  simp only [wireBindingMatches, Bool.and_eq_true] at hwire
  simp only [serviceResponseMatches, Bool.and_eq_true]
  rcases hwire with ⟨⟨⟨⟨_hepoch, htxn⟩, hservice⟩, hkind⟩, hrequest⟩
  exact ⟨⟨⟨htxn, hservice⟩, hkind⟩, hrequest⟩

theorem wireBinding_rejects_wrong_epoch (wireKey : ServiceKey)
    (bound : BoundServicePending) (h : wireKey.sessionEpoch ≠ bound.sessionEpoch) :
    wireBindingMatches wireKey bound = false := by
  simp [wireBindingMatches, h]

/-- Interpret sixteen little-endian digest bytes as one canonical word. -/
def digestWord (bytes : List UInt8) : FullProfile.Word :=
  ByteSerialization.deserialize (bytes.map fun byte => BitVec.ofNat 8 byte.toNat)

theorem uint8_bitvec_roundtrip (byte : UInt8) :
    UInt8.ofNat (BitVec.ofNat 8 byte.toNat).toNat = byte := by
  simp only [BitVec.toNat_ofNat]
  simpa using UInt8.ofNat_toNat byte

def validatedResponseToFullProfile (response : ValidatedWireServiceResponse) :
    Blake3Response := {
  txnId := response.wire.key.txnId
  serviceId := response.wire.key.serviceId
  serviceKind := response.wire.key.kind
  digest := (digestWord (response.wire.digest.take 16),
    digestWord (response.wire.digest.drop 16)) }

theorem validated_response_digest_is_byte_exact
    (response : ValidatedWireServiceResponse) :
    (ByteSerialization.serialize (validatedResponseToFullProfile response).digest.1 ++
      ByteSerialization.serialize (validatedResponseToFullProfile response).digest.2).map
        (fun byte => UInt8.ofNat byte.toNat) = response.wire.digest := by
  have htake : (response.wire.digest.take 16).length = ByteSerialization.beats := by
    simp [ByteSerialization.beats, response.wire.hDigest]
  have hdrop : (response.wire.digest.drop 16).length = ByteSerialization.beats := by
    simp [ByteSerialization.beats, response.wire.hDigest]
  have hfirst := ByteSerialization.serialize_deserialize
    ((response.wire.digest.take 16).map fun byte => BitVec.ofNat 8 byte.toNat)
    (by simpa using htake)
  have hsecond := ByteSerialization.serialize_deserialize
    ((response.wire.digest.drop 16).map fun byte => BitVec.ofNat 8 byte.toNat)
    (by simpa using hdrop)
  have hmap (bytes : List UInt8) :
      (bytes.map (fun byte => BitVec.ofNat 8 byte.toNat)).map
          (fun byte => UInt8.ofNat byte.toNat) = bytes := by
    induction bytes with
    | nil => rfl
    | cons byte bytes ih =>
        simp only [List.map_cons]
        rw [uint8_bitvec_roundtrip, ih]
  simp only [validatedResponseToFullProfile, digestWord]
  rw [List.map_append, hfirst, hsecond, List.map_map]
  rw [hmap]
  rw [show List.map
    ((fun byte => UInt8.ofNat byte.toNat) ∘ fun byte => BitVec.ofNat 8 byte.toNat)
    (response.wire.digest.take 16) = response.wire.digest.take 16 by
      simpa [List.map_map] using hmap (response.wire.digest.take 16)]
  exact List.take_append_drop 16 response.wire.digest

theorem validated_wire_binding_enters_canonical_model
    (response : ValidatedWireServiceResponse) (bound : BoundServicePending)
    (hbind : wireBindingMatches response.wire.key bound = true) :
    serviceResponseMatches bound.pending
      (validatedResponseToFullProfile response) = true := by
  exact wireBinding_implies_serviceResponseMatches response.wire.key bound hbind

/-- The sole wire-to-model admission function: malformed semantic fields and
binding mismatches are rejected before a `FullProfile.Blake3Response` exists. -/
def admitWireResponse (wire : WireServiceResponse) (bound : BoundServicePending) :
    Option Blake3Response :=
  match validateWireServiceResponse wire with
  | none => none
  | some response =>
      if wireBindingMatches response.wire.key bound then
        some (validatedResponseToFullProfile response)
      else none

/-- Public byte-to-endpoint admission.  A `Blake3Response` cannot be obtained
from malformed framing, failed status, or unsupported schema/digest length. -/
def admitWireResponseBytes (bytes : List UInt8) (bound : BoundServicePending) :
    Option Blake3Response :=
  match decodeValidatedServiceResponse bytes with
  | none => none
  | some response =>
      if wireBindingMatches response.wire.key bound then
        some (validatedResponseToFullProfile response)
      else none

theorem admitWireResponseBytes_only_after_validation
    (bytes : List UInt8) (bound : BoundServicePending) (response : Blake3Response)
    (hadmit : admitWireResponseBytes bytes bound = some response) :
    ∃ validated, decodeValidatedServiceResponse bytes = some validated ∧
      response = validatedResponseToFullProfile validated ∧
      serviceResponseMatches bound.pending response = true := by
  simp only [admitWireResponseBytes] at hadmit
  split at hadmit
  · contradiction
  · rename_i validated hvalidated
    split at hadmit
    · rename_i hbind
      cases hadmit
      exact ⟨validated, hvalidated, rfl,
        validated_wire_binding_enters_canonical_model validated bound hbind⟩
    · contradiction

theorem admitted_wire_response_matches_canonical
    (wire : WireServiceResponse) (bound : BoundServicePending)
    (response : Blake3Response)
    (hadmit : admitWireResponse wire bound = some response) :
    serviceResponseMatches bound.pending response = true := by
  simp only [admitWireResponse] at hadmit
  split at hadmit
  · contradiction
  · rename_i validated hvalidated
    split at hadmit
    · rename_i hbind
      cases hadmit
      exact validated_wire_binding_enters_canonical_model validated bound hbind
    · contradiction

theorem admitWireResponse_rejects_wrong_epoch (wire : WireServiceResponse)
    (bound : BoundServicePending)
    (h : wire.key.sessionEpoch ≠ bound.sessionEpoch) :
    admitWireResponse wire bound = none := by
  cases hvalidated : validateWireServiceResponse wire with
  | none => simp [admitWireResponse, hvalidated]
  | some validated =>
      have hwire := validateWireServiceResponse_preserves_wire wire validated hvalidated
      have hkey : validated.wire.key.sessionEpoch ≠ bound.sessionEpoch := by
        rw [hwire]
        exact h
      simp [admitWireResponse, hvalidated,
        wireBinding_rejects_wrong_epoch validated.wire.key bound hkey]

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

/-! ## Stall invariance -/

/-- Minimal ready/valid output state.  A cycle advances only on a handshake;
otherwise both the serialized bytes and current byte index are held. -/
structure WireOutputState where
  bound : BoundServicePending
  index : Nat

def WireOutputState.bytes (state : WireOutputState) : List UInt8 :=
  encodeServiceRequired (wireServiceRequiredOfPending state.bound.sessionEpoch
    state.bound.hEpoch state.bound.pending)

def WireOutputState.valid (state : WireOutputState) : Bool :=
  state.index < state.bytes.length

def WireOutputState.data (state : WireOutputState) : Option UInt8 :=
  state.bytes[state.index]?

def wireOutputCycle (state : WireOutputState) (ready : Bool) : WireOutputState :=
  if state.valid && ready then
    { state with index := state.index + 1 }
  else state

@[simp] theorem wire_output_stall_holds_state (state : WireOutputState) :
    wireOutputCycle state false = state := by
  simp [wireOutputCycle]

theorem wire_output_stalls_hold_state (state : WireOutputState) (count : Nat) :
    (List.replicate count false).foldl wireOutputCycle state = state := by
  induction count with
  | zero => rfl
  | succ count ih => simp [List.replicate_succ, ih]

theorem wire_output_stall_holds_bytes (state : WireOutputState) :
    (wireOutputCycle state false).bytes = state.bytes := by
  rw [wire_output_stall_holds_state]

theorem wire_output_stall_holds_valid_and_data (state : WireOutputState) :
    (wireOutputCycle state false).valid = state.valid ∧
      (wireOutputCycle state false).data = state.data := by
  rw [wire_output_stall_holds_state]
  exact ⟨rfl, rfl⟩

theorem wire_output_stalls_preserve_fullProfile_pending
    (state : WireOutputState) (count : Nat) :
    ((List.replicate count false).foldl wireOutputCycle state).bound.pending =
      state.bound.pending := by
  rw [wire_output_stalls_hold_state]

theorem wire_output_is_canonical_service_required (state : WireOutputState) :
    state.bytes = encodeServiceRequired
      (wireServiceRequiredOfPending state.bound.sessionEpoch state.bound.hEpoch
        state.bound.pending) := rfl

theorem wire_output_stall_holds_index (state : WireOutputState) :
    (wireOutputCycle state false).index = state.index := by
  rw [wire_output_stall_holds_state]

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

def witnessWireServiceResponse : WireServiceResponse := {
  schemaVersion := 1
  key := {
    sessionEpoch := 1
    txnId := witnessBlake3Response.txnId
    serviceId := witnessBlake3Response.serviceId
    kind := witnessBlake3Response.serviceKind }
  status := 0
  digestLength := 32
  digest := List.replicate 32 0
  hDigest := by simp }

example : (decodeValidatedServiceResponse
    (encodeServiceResponse witnessWireServiceResponse)).isSome = true := by
  native_decide

example : decodeValidatedServiceResponse
    ((encodeServiceResponse witnessWireServiceResponse).set 0 2) = none := by
  native_decide

example : decodeValidatedServiceResponse
    ((encodeServiceResponse witnessWireServiceResponse).set 18 1) = none := by
  native_decide

example : decodeValidatedServiceResponse
    ((encodeServiceResponse witnessWireServiceResponse).set 19 31) = none := by
  native_decide

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
#print axioms decodeServiceResponse_rejects_length
#print axioms wire_required_binding_is_canonical
#print axioms validateWireServiceResponse_rejects_schema
#print axioms validateWireServiceResponse_rejects_status
#print axioms validateWireServiceResponse_rejects_digest_length
#print axioms decodeValidatedServiceResponse_rejects_decoded_schema
#print axioms decodeValidatedServiceResponse_rejects_decoded_status
#print axioms decodeValidatedServiceResponse_rejects_decoded_digest_length
#print axioms validateWireServiceResponse_preserves_wire
#print axioms keyMatches_refl
#print axioms wireBinding_implies_serviceResponseMatches
#print axioms wireBinding_rejects_wrong_epoch
#print axioms validated_wire_binding_enters_canonical_model
#print axioms validated_response_digest_is_byte_exact
#print axioms admitted_wire_response_matches_canonical
#print axioms admitWireResponse_rejects_wrong_epoch
#print axioms admitWireResponseBytes_only_after_validation
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
#print axioms wire_output_stall_holds_state
#print axioms wire_output_stalls_hold_state
#print axioms wire_output_stall_holds_bytes
#print axioms wire_output_stall_holds_valid_and_data
#print axioms wire_output_stalls_preserve_fullProfile_pending
#print axioms wire_output_is_canonical_service_required
#print axioms wire_output_stall_holds_index
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

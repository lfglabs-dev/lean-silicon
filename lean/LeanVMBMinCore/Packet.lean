/-!
Executable, transport-independent model of the LSC-1 v1 request and response
envelopes.

The model deliberately leaves the checksum algorithm behind a stable function
parameter.  The production protocol instantiates it with CRC-32; later
refinement work can relate that implementation to `checksum` without changing
the packet, decoder, or transaction interfaces below.
-/

namespace LeanVMBMinCore.Packet

abbrev Byte := UInt8
abbrev Checksum := UInt32
abbrev ChecksumFn := List Byte → Checksum

def protocolVersion : Byte := 1
def requestSof : Byte := 0xa1
def responseSof : Byte := 0x5a
def maxPayloadBytes : Nat := 256

structure Request where
  opcode : Byte
  flags : Byte := 0
  payload : List Byte
  deriving DecidableEq, Repr

structure Response where
  status : Byte
  payload : List Byte
  deriving DecidableEq, Repr

structure RequestWire where
  sof : Byte
  version : Byte
  opcode : Byte
  flags : Byte
  declaredLength : Nat
  payload : List Byte
  checksum : Checksum
  deriving DecidableEq, Repr

structure ResponseWire where
  sof : Byte
  version : Byte
  status : Byte
  declaredLength : Nat
  payload : List Byte
  checksum : Checksum
  deriving DecidableEq, Repr

inductive DecodeError where
  | badSof
  | badVersion
  | badFlags
  | badLength
  | badChecksum
  deriving DecidableEq, Repr

def lengthBytes (length : Nat) : List Byte :=
  [UInt8.ofNat length, UInt8.ofNat (length / 256)]

def requestChecksumBody (frame : RequestWire) : List Byte :=
  [frame.sof, frame.version, frame.opcode, frame.flags] ++
    lengthBytes frame.declaredLength ++ frame.payload

def responseChecksumBody (frame : ResponseWire) : List Byte :=
  [frame.sof, frame.version, frame.status] ++
    lengthBytes frame.declaredLength ++ frame.payload

def encodeRequest (checksum : ChecksumFn) (request : Request) : RequestWire :=
  let frame : RequestWire := {
    sof := requestSof
    version := protocolVersion
    opcode := request.opcode
    flags := request.flags
    declaredLength := request.payload.length
    payload := request.payload
    checksum := 0
  }
  { frame with checksum := checksum (requestChecksumBody frame) }

def encodeResponse (checksum : ChecksumFn) (response : Response) : ResponseWire :=
  let frame : ResponseWire := {
    sof := responseSof
    version := protocolVersion
    status := response.status
    declaredLength := response.payload.length
    payload := response.payload
    checksum := 0
  }
  { frame with checksum := checksum (responseChecksumBody frame) }

/-- Validation order is part of the public contract. -/
def decodeRequest (checksum : ChecksumFn) (frame : RequestWire) :
    Except DecodeError Request :=
  if frame.sof != requestSof then .error .badSof
  else if frame.declaredLength > maxPayloadBytes then .error .badLength
  else if frame.checksum != checksum (requestChecksumBody frame) then .error .badChecksum
  else if frame.version != protocolVersion then .error .badVersion
  else if frame.flags != 0 then .error .badFlags
  else if frame.declaredLength != frame.payload.length then .error .badLength
  else .ok { opcode := frame.opcode, flags := frame.flags, payload := frame.payload }

/-- The response wire type has no flags field, matching the asymmetric v1 envelope. -/
def decodeResponse (checksum : ChecksumFn) (frame : ResponseWire) :
    Except DecodeError Response :=
  if frame.sof != responseSof then .error .badSof
  else if frame.declaredLength > maxPayloadBytes then .error .badLength
  else if frame.version != protocolVersion then .error .badVersion
  else if frame.declaredLength != frame.payload.length then .error .badLength
  else if frame.checksum != checksum (responseChecksumBody frame) then .error .badChecksum
  else .ok { status := frame.status, payload := frame.payload }

@[simp] theorem decode_encode_request (checksum : ChecksumFn) (opcode : Byte)
    (payload : List Byte) (hlength : payload.length ≤ maxPayloadBytes) :
    decodeRequest checksum (encodeRequest checksum {
      opcode := opcode, flags := 0, payload := payload
    }) = .ok { opcode := opcode, flags := 0, payload := payload } := by
  simp [decodeRequest, encodeRequest, requestChecksumBody, Nat.not_lt.mpr hlength]

@[simp] theorem decode_encode_response (checksum : ChecksumFn) (response : Response)
    (hlength : response.payload.length ≤ maxPayloadBytes) :
    decodeResponse checksum (encodeResponse checksum response) = .ok response := by
  simp [decodeResponse, encodeResponse, responseChecksumBody, Nat.not_lt.mpr hlength]

theorem bad_sof_precedes_other_request_errors (checksum : ChecksumFn)
    (frame : RequestWire) (h : frame.sof ≠ requestSof) :
    decodeRequest checksum frame = .error .badSof := by
  simp [decodeRequest, h]

theorem oversized_request_precedes_checksum_and_header_errors (checksum : ChecksumFn)
    (frame : RequestWire) (hsof : frame.sof = requestSof)
    (hlength : maxPayloadBytes < frame.declaredLength) :
    decodeRequest checksum frame = .error .badLength := by
  simp [decodeRequest, hsof, hlength]

theorem bad_checksum_precedes_request_version_flags_and_payload_length
    (checksum : ChecksumFn) (frame : RequestWire)
    (hsof : frame.sof = requestSof)
    (hlength : frame.declaredLength ≤ maxPayloadBytes)
    (hchecksum : frame.checksum ≠ checksum (requestChecksumBody frame)) :
    decodeRequest checksum frame = .error .badChecksum := by
  simp [decodeRequest, hsof, Nat.not_lt.mpr hlength, hchecksum]

theorem bad_version_precedes_request_flags_and_payload_length (checksum : ChecksumFn)
    (frame : RequestWire) (hsof : frame.sof = requestSof)
    (hlength : frame.declaredLength ≤ maxPayloadBytes)
    (hchecksum : frame.checksum = checksum (requestChecksumBody frame))
    (hver : frame.version ≠ protocolVersion) :
    decodeRequest checksum frame = .error .badVersion := by
  simp [decodeRequest, hsof, Nat.not_lt.mpr hlength, hchecksum, hver]

def exampleChecksum (bytes : List Byte) : Checksum :=
  bytes.foldl (fun acc byte => acc + byte.toUInt32) 0

example :
    decodeRequest exampleChecksum
      (encodeRequest exampleChecksum { opcode := 0x03, payload := [0x2a, 0x00] }) =
      .ok { opcode := 0x03, flags := 0, payload := [0x2a, 0x00] } := by
  exact decode_encode_request exampleChecksum 0x03 [0x2a, 0x00] (by decide)

example :
    decodeResponse exampleChecksum
      (encodeResponse exampleChecksum { status := 0x00, payload := [0x01] }) =
      .ok { status := 0x00, payload := [0x01] } := by
  exact decode_encode_response exampleChecksum { status := 0x00, payload := [0x01] }
    (by decide)

end LeanVMBMinCore.Packet

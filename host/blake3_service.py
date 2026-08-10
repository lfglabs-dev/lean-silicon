"""Transport-independent external BLAKE3 compression service primitives.

This module deliberately does not select UART, JTAG, sockets, or an RTL
transport.  It binds a logical service exchange to a host-created session
epoch and adapts the current v1 model payload at the software boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Protocol

from .protocol import protocol

SCHEMA_VERSION = 1
KNOWN_FLAGS = 0x7F
SERVICE_REQUIRED_BYTES = 131
SERVICE_RESPONSE_BYTES = 53


class ServiceInfrastructureError(RuntimeError):
    """The service could not run (tool/process/transport availability)."""


class ServiceSemanticError(ValueError):
    """A well-delivered service message or result violated the contract."""


class ServiceStatus(IntEnum):
    OK = 0
    TRANSIENT_FAILURE = 1
    PERMANENT_FAILURE = 2


class Blake3HostService(Protocol):
    """Canonical implementation boundary for host-owned BLAKE3 compression."""

    def compress(self, request: "ServiceRequired") -> bytes:
        """Return exactly the 32-byte chaining value for ``request``."""


class SoftwareBlake3HostService:
    """Auditable CPU implementation of :class:`Blake3HostService`."""

    def compress(self, request: "ServiceRequired") -> bytes:
        return compress(request)


def _u32(value: int) -> bytes:
    return value.to_bytes(4, "little")


@dataclass(frozen=True)
class ServiceKey:
    session_epoch: int
    txn_id: int
    service_id: int
    kind: int

    def __post_init__(self) -> None:
        if not 0 < self.session_epoch < 1 << 64:
            raise ServiceSemanticError("session_epoch must be a nonzero u64")
        if not 0 <= self.txn_id < 1 << 32:
            raise ServiceSemanticError("txn_id must be a u32")
        if not 0 <= self.service_id < 1 << 32:
            raise ServiceSemanticError("service_id must be a u32")
        if not 0 <= self.kind < 1 << 8:
            raise ServiceSemanticError("kind must be a u8")


@dataclass(frozen=True)
class ServiceRequired:
    key: ServiceKey
    message: bytes
    chaining_value: bytes
    counter: int
    block_len: int
    flags: int

    def __post_init__(self) -> None:
        if len(self.message) != 64 or len(self.chaining_value) != 32:
            raise ServiceSemanticError("BLAKE3 requires 64 message and 32 CV bytes")
        if not 0 <= self.counter < 1 << 64:
            raise ServiceSemanticError("counter must be a u64")
        if not 0 <= self.block_len <= 64:
            raise ServiceSemanticError("block_len must be in 0..64")
        if self.flags & ~KNOWN_FLAGS:
            raise ServiceSemanticError("unknown BLAKE3 flag bits")
        if self.key.kind != int(protocol.ServiceKind.BLAKE3_COMPRESS):
            raise ServiceSemanticError("unsupported service kind")

    def encode(self) -> bytes:
        return (
            bytes((SCHEMA_VERSION,))
            + self.key.session_epoch.to_bytes(8, "little")
            + _u32(self.key.txn_id) + _u32(self.key.service_id)
            + bytes((self.key.kind, 0))
            + self.message + self.chaining_value
            + self.counter.to_bytes(8, "little")
            + _u32(self.block_len) + _u32(self.flags)
        )

    @classmethod
    def decode(cls, payload: bytes) -> "ServiceRequired":
        if len(payload) != SERVICE_REQUIRED_BYTES:
            raise ServiceSemanticError("malformed SERVICE_REQUIRED length")
        if payload[0] != SCHEMA_VERSION or payload[18] != 0:
            raise ServiceSemanticError("unsupported version or nonzero reserved byte")
        key = ServiceKey(
            int.from_bytes(payload[1:9], "little"),
            int.from_bytes(payload[9:13], "little"),
            int.from_bytes(payload[13:17], "little"),
            payload[17],
        )
        return cls(
            key, payload[19:83], payload[83:115],
            int.from_bytes(payload[115:123], "little"),
            int.from_bytes(payload[123:127], "little"),
            int.from_bytes(payload[127:131], "little"),
        )

    @classmethod
    def from_v1(cls, payload: bytes, *, session_epoch: int) -> "ServiceRequired":
        if len(payload) != 122 or payload[9] != 0:
            raise ServiceSemanticError("malformed v1 SERVICE_REQUIRED payload")
        metadata = payload[106:122]
        return cls(
            ServiceKey(
                session_epoch,
                int.from_bytes(payload[0:4], "little"),
                int.from_bytes(payload[4:8], "little"),
                payload[8],
            ),
            payload[10:74], payload[74:106],
            int.from_bytes(metadata[0:8], "little"),
            int.from_bytes(metadata[8:12], "little"),
            int.from_bytes(metadata[12:16], "little"),
        )


@dataclass(frozen=True)
class ServiceResponse:
    key: ServiceKey
    status: ServiceStatus
    digest: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.status, ServiceStatus):
            raise ServiceSemanticError("unsupported service status")
        if len(self.digest) != 32:
            raise ServiceSemanticError("digest must be exactly 32 bytes")

    def encode(self) -> bytes:
        return (
            bytes((SCHEMA_VERSION,))
            + self.key.session_epoch.to_bytes(8, "little")
            + _u32(self.key.txn_id) + _u32(self.key.service_id)
            + bytes((self.key.kind, int(self.status)))
            + (32).to_bytes(2, "little") + self.digest
        )

    @classmethod
    def decode(cls, payload: bytes) -> "ServiceResponse":
        if len(payload) != SERVICE_RESPONSE_BYTES:
            raise ServiceSemanticError("malformed SERVICE_RESPONSE length")
        if payload[0] != SCHEMA_VERSION or int.from_bytes(payload[19:21], "little") != 32:
            raise ServiceSemanticError("unsupported version or malformed digest length")
        try:
            status = ServiceStatus(payload[18])
        except ValueError as exc:
            raise ServiceSemanticError("unsupported service status") from exc
        return cls(
            ServiceKey(
                int.from_bytes(payload[1:9], "little"),
                int.from_bytes(payload[9:13], "little"),
                int.from_bytes(payload[13:17], "little"),
                payload[17],
            ),
            status, payload[21:53],
        )


_IV = (0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
       0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19)
_PERM = (2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8)


def _rotr(value: int, count: int) -> int:
    return ((value >> count) | (value << (32 - count))) & 0xFFFFFFFF


def _g(state: list[int], a: int, b: int, c: int, d: int, x: int, y: int) -> None:
    state[a] = (state[a] + state[b] + x) & 0xFFFFFFFF
    state[d] = _rotr(state[d] ^ state[a], 16)
    state[c] = (state[c] + state[d]) & 0xFFFFFFFF
    state[b] = _rotr(state[b] ^ state[c], 12)
    state[a] = (state[a] + state[b] + y) & 0xFFFFFFFF
    state[d] = _rotr(state[d] ^ state[a], 8)
    state[c] = (state[c] + state[d]) & 0xFFFFFFFF
    state[b] = _rotr(state[b] ^ state[c], 7)


def compress(request: ServiceRequired) -> bytes:
    """Return the 32-byte chaining value for one BLAKE3 compression."""
    cv = [int.from_bytes(request.chaining_value[i:i + 4], "little")
          for i in range(0, 32, 4)]
    words = [int.from_bytes(request.message[i:i + 4], "little")
             for i in range(0, 64, 4)]
    state = cv + list(_IV[:4]) + [
        request.counter & 0xFFFFFFFF, request.counter >> 32,
        request.block_len, request.flags,
    ]
    schedule = list(range(16))
    for _ in range(7):
        m = [words[i] for i in schedule]
        _g(state, 0, 4, 8, 12, m[0], m[1])
        _g(state, 1, 5, 9, 13, m[2], m[3])
        _g(state, 2, 6, 10, 14, m[4], m[5])
        _g(state, 3, 7, 11, 15, m[6], m[7])
        _g(state, 0, 5, 10, 15, m[8], m[9])
        _g(state, 1, 6, 11, 12, m[10], m[11])
        _g(state, 2, 7, 8, 13, m[12], m[13])
        _g(state, 3, 4, 9, 14, m[14], m[15])
        schedule = [schedule[i] for i in _PERM]
    return b"".join(((state[i] ^ state[i + 8]) & 0xFFFFFFFF).to_bytes(4, "little")
                    for i in range(8))


class ModelServiceAdapter:
    """Epoch/replay guard and bounded-retry adapter for the executable model."""

    def __init__(self, session_epoch: int, *, max_retries: int = 2) -> None:
        if not 0 < session_epoch < 1 << 64:
            raise ValueError("session_epoch must be a nonzero u64")
        if max_retries < 0:
            raise ValueError("max_retries must be nonnegative")
        self.session_epoch = session_epoch
        self._used_epochs = {session_epoch}
        self.max_retries = max_retries
        self.outstanding: ServiceKey | None = None
        self._outstanding_request: ServiceRequired | None = None
        self.completed: set[ServiceKey] = set()

    def accept_required(self, payload: bytes) -> ServiceRequired:
        request = ServiceRequired.from_v1(payload, session_epoch=self.session_epoch)
        if self.outstanding is not None:
            if request.key != self.outstanding:
                raise ServiceSemanticError("another service transaction is outstanding")
            if request != self._outstanding_request:
                raise ServiceSemanticError("retry changed service operands")
        elif request.key in self.completed:
            raise ServiceSemanticError("replayed SERVICE_REQUIRED")
        else:
            self.outstanding = request.key
            self._outstanding_request = request
        return request

    def compute(self, request: ServiceRequired,
                service: Callable[[ServiceRequired], bytes] = compress) -> ServiceResponse:
        if request != self._outstanding_request:
            raise ServiceSemanticError("request is stale or not outstanding")
        for attempt in range(self.max_retries + 1):
            try:
                digest = service(request)
                if not isinstance(digest, bytes) or len(digest) != 32:
                    raise ServiceSemanticError("service returned a non-bytes or wrong-length digest")
                return ServiceResponse(request.key, ServiceStatus.OK, digest)
            except ServiceInfrastructureError:
                if attempt == self.max_retries:
                    raise
        raise AssertionError("unreachable")

    def to_v1(self, response: ServiceResponse) -> "protocol.RequestFrame":
        if response.key != self.outstanding:
            raise ServiceSemanticError("stale or wrongly bound SERVICE_RESPONSE")
        if response.status is not ServiceStatus.OK:
            raise ServiceSemanticError("failed service response cannot reach the model")
        digest = (
            int.from_bytes(response.digest[:16], "little"),
            int.from_bytes(response.digest[16:], "little"),
        )
        return protocol.build_service_response(
            txn_id=response.key.txn_id,
            service_id=response.key.service_id,
            kind=protocol.ServiceKind(response.key.kind),
            digest=digest,
        )

    def complete(self, key: ServiceKey) -> None:
        if key != self.outstanding:
            raise ServiceSemanticError("cannot complete a stale service")
        self.completed.add(key)
        self.outstanding = None
        self._outstanding_request = None

    def abort(self) -> None:
        if self.outstanding is not None:
            self.completed.add(self.outstanding)
        self.outstanding = None
        self._outstanding_request = None

    def reset(self, new_session_epoch: int) -> None:
        if not 0 < new_session_epoch < 1 << 64:
            raise ValueError("session_epoch must be a nonzero u64")
        if new_session_epoch in self._used_epochs:
            raise ValueError("reset requires an epoch never used by this adapter")
        self._used_epochs.add(new_session_epoch)
        self.session_epoch = new_session_epoch
        self.outstanding = None
        self._outstanding_request = None
        self.completed.clear()

"""Host-side error taxonomy.

Every capability the host runtime does not yet implement raises
``UnsupportedCapability`` naming the exact missing piece.  Nothing in this
package silently degrades, skips an instruction, or invents a result.
"""

from __future__ import annotations


class HostError(Exception):
    """Base class for every failure raised by the host runtime."""


class UnsupportedCapability(HostError):
    """A capability this scaffold has deliberately not integrated yet."""


class AdapterError(HostError):
    """A program artifact that the lean_compiler adapter refuses to load."""


class WriteOnceViolation(HostError):
    """The host was asked to overwrite a written cell with a different value."""


class ProtocolViolation(HostError):
    """A response was well-framed but violated the transaction contract."""


class TransactionRejected(HostError):
    """The endpoint answered an instruction with a fault status."""

    def __init__(self, status, detail: bytes = b"") -> None:
        super().__init__(f"endpoint rejected the transaction: {status.name}")
        self.status = status
        self.detail = detail

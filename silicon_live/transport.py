"""Transport adapters. Importing this module never opens or enumerates a port."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol


def encode_request(kind: str, inputs: tuple[int, ...]) -> bytes:
    """Encode the exact historical candidate framing (no later ABORT prefix)."""
    from fpga_harness.ulx3s_uart import encode_request as pr16_encode
    values = [v.to_bytes(16, "little") for v in inputs]
    if kind == "Set":
        return pr16_encode("set", value=values[0], include_resync=False)
    return pr16_encode(kind.lower(), a=values[0], b=values[1], include_resync=False)


class ArithmeticTransport(Protocol):
    def exchange(self, operation: str, *, a: bytes = b"", b: bytes = b"",
                 value: bytes = b"") -> tuple[bytes, bytes]: ...


class HostRuntimeTransport:
    """Board-free arithmetic model with the same exchange boundary as PR #16."""

    def exchange(self, operation: str, *, a: bytes = b"", b: bytes = b"",
                 value: bytes = b"") -> tuple[bytes, bytes]:
        from host.protocol import protocol
        if operation == "set":
            inputs, response = (int.from_bytes(value, "little"),), value
        elif operation in {"xor", "mul"}:
            left, right = int.from_bytes(a, "little"), int.from_bytes(b, "little")
            result = left ^ right if operation == "xor" else protocol.field_mul(left, right)
            inputs, response = (left, right), result.to_bytes(16, "little")
        else:
            raise ValueError(f"host model does not implement {operation}")
        request = encode_request(operation.title(), inputs)
        return request, response


@dataclass
class FakeSerial:
    """Small pyserial-compatible fake used by adapter tests and demos."""
    response: bytes
    written: bytearray = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.written = bytearray()

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def read(self, size: int) -> bytes:
        chunk, self.response = self.response[:size], self.response[size:]
        return chunk


class LiveFPGATransport:
    """Explicit wrapper around PR #16; caller supplies an already-open serial object."""
    def __init__(self, serial_object: object, timeout: float = 1.0) -> None:
        from fpga_harness.ulx3s_uart import MinCoreSerialDriver
        self._driver = MinCoreSerialDriver(serial_object, timeout)

    def exchange(self, operation: str, **values: bytes) -> tuple[bytes, bytes]:
        return self._driver.exchange(operation, **values)

"""Physical LSC-1 packet-v1 transport over the ULX3S 1 Mbaud UART."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from host.errors import HostError
from host.lean_compiler_adapter import load as load_program
from host.protocol import protocol
from host.runtime import HostRuntime, decode_result_payload


class PacketTransportError(RuntimeError):
    pass


class ByteTransport(Protocol):
    timeout: float | None

    def read(self, size: int) -> bytes: ...
    def write(self, data: bytes) -> int: ...
    def flush(self) -> None: ...


@dataclass(frozen=True)
class Exchange:
    request: bytes
    response: bytes
    duration_ns: int


class PacketSerialDriver:
    def __init__(self, transport: ByteTransport, timeout: float = 2.0, baud: int = 1_000_000):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.transport = transport
        self.timeout = timeout
        self.baud = baud
        self.exchanges: list[Exchange] = []

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PacketTransportError("packet response deadline expired")
        return remaining

    def _read_exact(self, size: int, deadline: float) -> bytes:
        data = bytearray()
        while len(data) < size:
            remaining = self._remaining(deadline)
            if hasattr(self.transport, "timeout"):
                self.transport.timeout = min(remaining, 0.1)
            chunk = self.transport.read(size - len(data))
            if chunk:
                data.extend(chunk)
        return bytes(data)

    def _write_all(self, data: bytes, deadline: float) -> None:
        offset = 0
        while offset < len(data):
            self._remaining(deadline)
            count = self.transport.write(data[offset:])
            if not isinstance(count, int) or count <= 0:
                raise PacketTransportError("packet write made no progress")
            offset += count
        self.transport.flush()

    def drain(self) -> bytes:
        drained = bytearray()
        waiting = getattr(self.transport, "in_waiting", 0)
        while waiting:
            chunk = self.transport.read(waiting)
            if not chunk:
                raise PacketTransportError("stale-byte drain made no progress")
            drained.extend(chunk)
            waiting = getattr(self.transport, "in_waiting", 0)
        return bytes(drained)

    def abort(self) -> None:
        send_break = getattr(self.transport, "send_break", None)
        if not callable(send_break):
            raise PacketTransportError("transport cannot issue the out-of-band UART BREAK abort")
        send_break(duration=0.002)
        time.sleep(0.003)
        self.drain()

    def exchange_encoded(self, request: bytes) -> protocol.ResponseFrame:
        """Exchange an already encoded frame, including adversarial test bytes."""
        if not request:
            raise ValueError("encoded request must not be empty")
        self.drain()
        deadline = time.monotonic() + self.timeout
        started = time.monotonic_ns()
        self._write_all(request, deadline)
        header = self._read_exact(protocol.RESPONSE_HEADER_BYTES, deadline)
        length = int.from_bytes(header[3:5], "little")
        if length > protocol.MAX_PAYLOAD_BYTES:
            raise PacketTransportError(f"response payload length {length} exceeds v1 maximum")
        response = header + self._read_exact(length + protocol.CRC_BYTES, deadline)
        decoded = protocol.decode_response(response)
        # One byte takes ten UART symbols. Let a surplus byte become visible.
        time.sleep(12 / self.baud)
        extra = self.drain()
        if extra:
            raise PacketTransportError(f"surplus response bytes: {extra.hex()}")
        self.exchanges.append(Exchange(request, response, time.monotonic_ns() - started))
        return decoded

    def exchange(self, frame: protocol.RequestFrame) -> protocol.ResponseFrame:
        return self.exchange_encoded(frame.encode())


PACKET_RTL_FEATURES = 0b010


def _validate_capabilities(payload: bytes, profile: protocol.Profile) -> None:
    if len(payload) != 14:
        raise PacketTransportError("NEGOTIATE did not return the 14-byte schema")
    features = int.from_bytes(payload[6:10], "little")
    if (
        payload[0] != protocol.PROTOCOL_VERSION
        or payload[1] != int(profile)
        or int.from_bytes(payload[2:4], "little") != protocol.MAX_PAYLOAD_BYTES
        or payload[4] != protocol.INDEX_BITS
        or payload[5] != 0
        or int.from_bytes(payload[10:14], "little") != protocol.DEVICE_ID
        or features & PACKET_RTL_FEATURES != PACKET_RTL_FEATURES
    ):
        raise PacketTransportError(f"unexpected packet RTL capabilities: {payload.hex()}")


class PhysicalHostRuntime(HostRuntime):
    """Run the canonical host transaction loop over a physical packet lane."""

    def __init__(self, program, driver: PacketSerialDriver):
        self.driver = driver
        super().__init__(program, profile=protocol.Profile.INTERPRETER_COMPAT)

    def _exchange(self, frame: protocol.RequestFrame) -> protocol.ResponseFrame:
        reply = self.driver.exchange(frame)
        exchange = self.driver.exchanges[-1]
        self.lane_cycles += len(exchange.request) + len(exchange.response)
        return reply

    def _negotiate(self) -> None:
        reply = self._exchange(protocol.build_negotiate(profile=self.profile))
        if reply.status is not protocol.Status.OK:
            raise PacketTransportError(f"NEGOTIATE returned {reply.status.name}")
        _validate_capabilities(reply.payload, self.profile)


def _physical_transport(port: str, baud: int, timeout: float):
    try:
        import serial
    except ImportError as error:  # pragma: no cover - environment boundary
        raise PacketTransportError("physical mode requires pyserial") from error
    try:
        return serial.Serial(port, baudrate=baud, timeout=min(timeout, 0.1), write_timeout=timeout)
    except Exception as error:
        raise PacketTransportError("could not open the requested serial port") from error


def _instruction_frame(args: argparse.Namespace) -> tuple[protocol.RequestFrame, int]:
    common = dict(
        txn_id=args.txn_id,
        pc=args.pc,
        fp=args.fp,
        profile=protocol.Profile.INTERPRETER_COMPAT,
    )
    if args.operation == "set":
        return protocol.build_set_constant(
            **common, offset=0, constant=args.value, cell=protocol.ABSENT
        ), args.value
    opcode = protocol.Opcode.XOR if args.operation == "xor" else protocol.Opcode.MUL_NATIVE
    expected = args.a ^ args.b if opcode is protocol.Opcode.XOR else protocol.field_mul(args.a, args.b)
    return protocol.build_binary_op(
        opcode, **common, offsets=(0, 1, 2),
        cells=(protocol.Cell(True, args.a), protocol.Cell(True, args.b), protocol.ABSENT),
    ), expected


def _run(args: argparse.Namespace) -> dict:
    transport = _physical_transport(args.port, args.baud, args.timeout)
    try:
        driver = PacketSerialDriver(transport, args.timeout, args.baud)
        driver.abort()
        if args.operation == "program":
            program = load_program(args.program_artifact)
            runtime = PhysicalHostRuntime(program, driver)
            run = runtime.run(max_steps=args.max_steps)
            result = {
                "terminal": run.terminal,
                "reason": run.reason,
                "run": run.as_dict(),
                "final_state": runtime.final_state(args.memory_cells),
            }
            result["exchanges"] = [
                {
                    "request_hex": item.request.hex(),
                    "response_hex": item.response.hex(),
                    "duration_ns": item.duration_ns,
                }
                for item in driver.exchanges
            ]
            return result
        negotiate = driver.exchange(protocol.build_negotiate(
            profile=protocol.Profile.INTERPRETER_COMPAT
        ))
        if negotiate.status is not protocol.Status.OK:
            raise PacketTransportError(f"NEGOTIATE returned {negotiate.status.name}")
        _validate_capabilities(negotiate.payload, protocol.Profile.INTERPRETER_COMPAT)
        if args.operation == "status":
            reply = driver.exchange(protocol.build_status_query())
            if reply.status is not protocol.Status.INFO or len(reply.payload) != 20:
                raise PacketTransportError("STATUS_QUERY did not return the 20-byte INFO schema")
            result = {"status": reply.status.name, "payload_hex": reply.payload.hex()}
        else:
            frame, expected = _instruction_frame(args)
            reply = driver.exchange(frame)
            if reply.status is not protocol.Status.OK:
                raise PacketTransportError(f"instruction returned {reply.status.name}")
            decoded = decode_result_payload(reply.payload, expected_txn_id=args.txn_id)
            writes = decoded["writes"]
            if len(writes) != 1 or writes[0]["value"] != expected:
                raise PacketTransportError("result write does not match the independent host oracle")
            retired = driver.exchange(protocol.build_retire(
                txn_id=args.txn_id, result_crc=protocol.crc32(reply.payload)
            ))
            if retired.status is not protocol.Status.RETIRED:
                raise PacketTransportError(f"RETIRE returned {retired.status.name}")
            result = {
                "status": reply.status.name,
                "retire_status": retired.status.name,
                "result": decoded,
                "expected": f"0x{expected:032x}",
            }
        result["exchanges"] = [
            {
                "request_hex": item.request.hex(),
                "response_hex": item.response.hex(),
                "duration_ns": item.duration_ns,
            }
            for item in driver.exchanges
        ]
        return result
    finally:
        transport.close()


def _field(value: str) -> int:
    parsed = int(value, 0)
    if not 0 <= parsed < 1 << 128:
        raise argparse.ArgumentTypeError("field value must fit in 128 bits")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument(
        "--operation", choices=("status", "set", "xor", "mul", "program"),
        default="status",
    )
    parser.add_argument("--txn-id", type=int, default=1)
    parser.add_argument("--pc", type=int, default=0)
    parser.add_argument("--fp", type=int, default=0)
    parser.add_argument("--value", type=_field, default=3)
    parser.add_argument("--a", type=_field, default=3)
    parser.add_argument("--b", type=_field, default=5)
    parser.add_argument(
        "--program-artifact", type=Path,
        default=Path("host/fixtures/assert_set_xor_mul.program.json"),
    )
    parser.add_argument("--max-steps", type=int, default=1024)
    parser.add_argument("--memory-cells", type=int, default=16)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args(argv)
    try:
        result = _run(args)
        encoded = json.dumps(result, indent=2, sort_keys=True)
        print(encoded)
        if args.evidence:
            args.evidence.write_text(encoded + "\n")
        return 0
    except (HostError, PacketTransportError, protocol.ProtocolFault, ValueError) as error:
        print(f"lsc1-packet-uart: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

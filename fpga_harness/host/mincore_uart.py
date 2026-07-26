#!/usr/bin/env python3
"""Deliberately small host diagnostic transport for the historical MinCore lane.

This module does not implement LSC-1 framing.  It sends the fixed-length
MinCore byte grammar through a UART bridge which presents a transparent byte
stream, and never retries a transaction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Dict, Optional, Protocol, Sequence

VERSION = "0.1.0"
STATUS_BYTES = bytes.fromhex("01010f08")


class MinCoreError(Exception):
    """Base error for a diagnostic exchange.

    `observed` carries the response bytes that did arrive before the failure so
    a caller can record what the device actually returned.  Reporting an empty
    response for a rejected or partial answer would claim the wire stayed
    silent when it did not.
    """

    def __init__(self, *args: object, observed: bytes = b"") -> None:
        super().__init__(*args)
        self.observed = observed


class TransportTimeout(MinCoreError):
    """A write or read did not make progress before the configured deadline."""


class ResponseError(MinCoreError):
    """A response has the wrong size or violates a fixed response contract."""


class AbortUnavailable(MinCoreError):
    """The raw serial byte stream cannot assert MinCore's hardware ABORT pin."""


class TransportFailure(MinCoreError):
    """The transport raised an I/O error without a safe retry path."""


class ByteTransport(Protocol):
    @property
    def in_waiting(self) -> int: ...

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int: ...


@dataclass(frozen=True)
class Vector:
    name: str
    operation: str
    a: bytes = b""
    b: bytes = b""
    value: bytes = b""
    expected: bytes = b""


# These literals were independently checked by polynomial long reduction.
# They intentionally do not call this module's encode/decode implementation.
VECTORS: Dict[str, Vector] = {
    "set128": Vector(
        "set128", "set", value=bytes.fromhex("000102030405060708090a0b0c0d0e0f"),
        expected=bytes.fromhex("000102030405060708090a0b0c0d0e0f"),
    ),
    "xor128": Vector(
        "xor128", "xor", a=bytes.fromhex("000102030405060708090a0b0c0d0e0f"),
        b=bytes.fromhex("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff"),
        expected=bytes.fromhex("f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0"),
    ),
    "mul128": Vector(
        "mul128", "mul", a=bytes.fromhex("00112233445566778899aabbccddeeff"),
        b=bytes.fromhex("ffeeddccbbaa99887766554433221100"),
        expected=bytes.fromhex("c043248e79cfa802850661cb3c8aed47"),
    ),
}


def _require_16(label: str, value: bytes) -> bytes:
    if len(value) != 16:
        raise ValueError(f"{label} must contain exactly 16 bytes (32 hex digits)")
    return value


def response_length(operation: str) -> int:
    return {"xor": 16, "mul": 16, "set": 16, "status": 4, "clear": 0}[operation]


def encode_request(operation: str, *, a: bytes = b"", b: bytes = b"", value: bytes = b"") -> bytes:
    """Encode exactly one raw MinCore request; F128 arguments are little-endian."""
    if operation == "xor":
        a, b = _require_16("a", a), _require_16("b", b)
        return bytes((0x01,)) + bytes(x for pair in zip(a, b) for x in pair)
    if operation == "mul":
        return bytes((0x02,)) + _require_16("a", a) + _require_16("b", b)
    if operation == "set":
        return bytes((0x03,)) + _require_16("value", value)
    if operation == "clear":
        return bytes((0x7D,))
    if operation == "status":
        return bytes((0x7E,))
    raise ValueError(f"unsupported operation: {operation}")


def decode_response(operation: str, response: bytes) -> bytes:
    """Validate a fixed-size response.  STATUS is the only fixed-value response."""
    needed = response_length(operation)
    if len(response) != needed:
        raise ResponseError(f"{operation} response length {len(response)}, expected {needed}",
                            observed=response)
    if operation == "status" and response != STATUS_BYTES:
        raise ResponseError(f"STATUS response {response.hex()}, expected {STATUS_BYTES.hex()}",
                            observed=response)
    return response


class MinCoreDriver:
    def __init__(self, transport: ByteTransport, timeout: float = 1.0, clock: Callable[[], float] = time.monotonic):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        self.transport, self.timeout, self.clock = transport, timeout, clock
        self._usable = True

    def _buffered_count(self, budget: float, timeout_message: str) -> int:
        """Query buffered RX bytes; pyserial raises I/O errors from this property.

        The property is a backend query that can block on a stalled or
        disconnecting device, so it is bounded like every other transport call.
        """
        try:
            buffered = int(self._bounded(lambda: getattr(self.transport, "in_waiting", 0), budget, timeout_message))
        except TransportTimeout:
            raise
        except Exception as error:
            raise TransportFailure("buffered-input query failed") from error
        return max(0, buffered)

    def _deadline(self, deadline: Optional[float]) -> float:
        """Adopt the caller's transaction budget, or open a fresh one when alone."""
        return self.clock() + self.timeout if deadline is None else deadline

    def drain_stale(self, deadline: Optional[float] = None) -> bytes:
        """Remove already-buffered RX bytes before one diagnostic exchange.

        The buffered-count query and the drain read are both backend calls that
        can block on a stalled device, so each runs under what is left of the
        transaction budget instead of being checked only once it returns.  The
        budget is re-read between them so that a slow query is charged against
        the read that follows it rather than granting it a stale allowance.

        The drain is complete only when the device reports nothing buffered, and
        a failure carries the bytes this drain already consumed so a caller can
        report them instead of dropping the evidence of what arrived.
        """
        deadline, drained = self._deadline(deadline), bytearray()
        while True:
            message = f"stale-input drain timeout after {len(drained)} bytes"
            try:
                if (buffered := self._buffered_count(deadline - self.clock(), message)) <= 0:
                    break
                chunk = self._bounded(lambda: self.transport.read(min(buffered, 4096)),
                                      deadline - self.clock(), message)
            except TransportTimeout as error:
                self._usable = False  # an abandoned call may still consume bytes later
                error.observed = bytes(drained)
                raise
            except TransportFailure as error:
                self._usable = False
                error.observed = bytes(drained)
                raise
            except Exception as error:
                self._usable = False  # the unread buffered bytes stay on the wire
                raise TransportFailure(f"stale-input drain failed after {len(drained)} bytes",
                                       observed=bytes(drained)) from error
            # A read that returns nothing while bytes are still reported buffered
            # made zero progress, so it is retried under the same budget.  Ending
            # the drain there would leave those bytes to contaminate the response
            # that follows, or let an immediately reported extra byte pass as none.
            if chunk:
                drained.extend(chunk)
        return bytes(drained)

    def _bounded(self, call: Callable[[], object], budget: float, timeout_message: str) -> object:
        """Run one blocking transport call under what is left of the budget.

        A synchronous call cannot be interrupted, so it runs on a daemon worker
        and is abandoned once the budget is gone.  Every path that abandons a
        call also leaves the driver poisoned, so an abandoned write can never be
        mistaken for part of a later exchange.  The caller passes a remaining
        budget rather than a deadline so that one call costs one clock read.

        An exhausted budget starts nothing: a worker launched only to be joined
        for zero seconds would keep running against a transport the caller is
        already tearing down.
        """
        if budget <= 0:
            raise TransportTimeout(timeout_message)
        outcome: list = []
        failures: list = []

        def run() -> None:
            try:
                outcome.append(call())
            except BaseException as error:  # reported on the calling thread
                failures.append(error)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(max(0.0, budget))
        if worker.is_alive():
            raise TransportTimeout(timeout_message)
        if failures:
            raise failures[0]
        return outcome[0]

    def _write_all(self, data: bytes, deadline: Optional[float] = None) -> None:
        deadline, offset = self._deadline(deadline), 0
        while offset < len(data):
            message = f"write timeout after {offset}/{len(data)} request bytes"
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise TransportTimeout(message)
            try:
                written = self._bounded(lambda: self.transport.write(data[offset:]), remaining, message)
            except TransportTimeout:
                raise
            except Exception as error:
                raise TransportFailure(f"write failed after {offset}/{len(data)} request bytes; transaction was not retried") from error
            if written is None:
                written = len(data) - offset
            if not isinstance(written, int) or written < 0 or written > len(data) - offset:
                raise TransportFailure(
                    f"transport reported invalid write count after {offset}/{len(data)} request bytes"
                )
            offset += written

    def _read_exact(self, size: int, deadline: Optional[float] = None) -> bytes:
        deadline, data = self._deadline(deadline), bytearray()
        while len(data) < size:
            message = f"read timeout after {len(data)}/{size} response bytes"
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise TransportTimeout(message, observed=bytes(data))
            try:
                chunk = self._bounded(lambda: self.transport.read(size - len(data)), remaining, message)
            except TransportTimeout as error:
                raise TransportTimeout(message, observed=bytes(data)) from error
            except Exception as error:
                raise TransportFailure(f"read failed after {len(data)}/{size} response bytes; transaction was not retried",
                                       observed=bytes(data)) from error
            if chunk:
                if len(chunk) > size - len(data):
                    raise TransportFailure(
                        f"transport returned too many bytes after {len(data)}/{size} response bytes",
                        observed=bytes(data) + bytes(chunk),
                    )
                data.extend(chunk)
                if self.clock() > deadline:
                    raise TransportTimeout(f"read timeout after {len(data)}/{size} response bytes",
                                           observed=bytes(data))
                continue
            if self.clock() >= deadline:
                raise TransportTimeout(f"read timeout after {len(data)}/{size} response bytes",
                                       observed=bytes(data))
        return bytes(data)

    def _flush_output(self, deadline: Optional[float] = None) -> None:
        """A zero-length response is no evidence that queued bytes actually left.

        `serial.Serial.flush()` is `tcdrain()`, which takes no timeout and blocks
        while a stalled device never drains, so it runs on a worker thread and is
        bounded by whatever remains of the transaction budget.
        """
        flush = getattr(self.transport, "flush", None)
        if not callable(flush):
            return
        deadline = self._deadline(deadline)
        try:
            self._bounded(flush, deadline - self.clock(),
                          "flush timeout before the no-response request drained")
        except TransportTimeout:
            raise
        except Exception as error:
            raise TransportFailure("output flush failed; transaction was not retried") from error

    def _reject_buffered_extra(self, deadline: Optional[float] = None, response: bytes = b"") -> None:
        """Reject bytes still buffered once a complete response has been accepted.

        A drain that fails partway has already consumed bytes the device sent
        after this request, so they are reported together with the response:
        those bytes are the evidence that framing was lost, and recording only
        the accepted fixed-length response would omit it.
        """
        try:
            extra = self.drain_stale(deadline)
        except MinCoreError as error:
            error.observed = response + error.observed
            raise
        if extra:
            raise ResponseError(f"unexpected buffered response bytes: {extra.hex()}",
                                observed=response + extra)

    def exchange(self, operation: str, *, a: bytes = b"", b: bytes = b"", value: bytes = b"") -> tuple[bytes, bytes]:
        """Send one request exactly once, then read and validate exactly one response.

        Arguments are validated before the window opens because encoding touches
        no bytes, and the preflight drain is inside it: a drain that fails or
        times out leaves an unknown number of stale bytes on the wire, which a
        later exchange would otherwise read back as this request's response.

        Every phase shares one deadline, so `timeout` bounds the whole
        transaction.  Per-phase deadlines would let a drain, write, read, and
        flush that each stay just inside the limit sum to several multiples of
        it, and the caller has no other handle on how long an exchange may run.
        """
        if not self._usable:
            raise TransportFailure(
                "driver is unusable after an indeterminate exchange; create a new transport after explicit resynchronization"
            )
        request = encode_request(operation, a=a, b=b, value=value)
        self._usable = False
        deadline = self.clock() + self.timeout
        response = b""
        try:
            try:
                self.drain_stale(deadline)
            except MinCoreError as error:
                # Stale bytes predate the request, so they are not a response to
                # it; reporting them as one would claim an observation this
                # exchange never made.
                error.observed = b""
                raise
            self._write_all(request, deadline)
            needed = response_length(operation)
            if needed == 0:
                self._flush_output(deadline)
            response = self._read_exact(needed, deadline)
            decode_response(operation, response)
            self._reject_buffered_extra(deadline, response)
        except MinCoreError as error:
            if not error.observed:
                error.observed = response
            raise
        else:
            self._usable = True
        return request, response

    def abort(self) -> None:
        abort_method = getattr(self.transport, "abort", None)
        if not callable(abort_method):
            raise AbortUnavailable("ABORT is a separate synchronous hardware pin; raw UART has no abort byte")
        abort_method()


def repo_provenance(evidence: Optional[Path] = None) -> tuple[str, Optional[bool]]:
    """Head commit plus whether that tree had uncommitted changes.

    A head alone cannot distinguish evidence produced by a modified checkout
    from a clean run at the same commit.  A null dirty flag means unknown, which
    must not be read as clean.  An *untracked* evidence file written inside the
    checkout is this tool's own output, not a source change, so it never counts
    as dirty.  A tracked destination is excluded from nothing: its edits are
    indistinguishable from source edits, so hiding them would let any modified
    file be laundered clean by naming it as the evidence path.
    """
    root = Path(__file__).resolve().parents[2]
    command = ["git", "status", "--porcelain=v1", "--untracked-files=all"]
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        if evidence is not None:
            try:
                relative = evidence.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                relative = ""  # outside the checkout, so git already ignores it
            if relative and not subprocess.check_output(
                ["git", "ls-files", "--", relative], cwd=root, text=True
            ).strip():
                command += ["--", ".", f":(exclude,literal,top){relative}"]
        status = subprocess.check_output(command, cwd=root, text=True)
    except (OSError, subprocess.CalledProcessError):
        return "unknown", None
    return head, bool(status.strip())


def record_evidence(
    stream: BinaryIO,
    *,
    provenance: tuple[str, Optional[bool]],
    operation: str,
    request: bytes,
    response: bytes,
    expected: Optional[bytes],
    passed: Optional[bool],
    execution_attempted: bool,
    serial_response_observed: bool,
    failure: Optional[str] = None,
    include_payloads: bool = False,
) -> None:
    """Write one JSONL record without a port or raw payloads by default.

    `failure` carries the exception class name only.  Transport error text can
    embed a device name, so the class is the widest discriminator that stays
    redacted.
    """
    digest = lambda value: hashlib.sha256(value).hexdigest()
    head, dirty = provenance
    record = {"tool_version": VERSION, "repo_head": head, "repo_dirty": dirty, "operation": operation,
              "request_length": len(request), "request_sha256": digest(request),
              "response_length": len(response), "response_sha256": digest(response),
              "expected_length": None if expected is None else len(expected),
              "expected_sha256": None if expected is None else digest(expected),
              "pass": passed, "execution_attempted": execution_attempted,
              "serial_response_observed": serial_response_observed,
              "failure": failure}
    if include_payloads:
        record.update(request_hex=request.hex(), response_hex=response.hex(),
                      expected_hex=None if expected is None else expected.hex())
    stream.write((json.dumps(record, sort_keys=True) + "\n").encode("utf-8"))
    stream.flush()


def _hex_arg(value: str) -> bytes:
    try:
        return bytes.fromhex(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an even-length hexadecimal string") from error


def _positive_finite(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive finite number") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return parsed


def _baud_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer from 1 through 4000000") from error
    if not 1 <= parsed <= 4_000_000:
        raise argparse.ArgumentTypeError("must be an integer from 1 through 4000000")
    return parsed


def _operation_inputs(args: argparse.Namespace) -> tuple[bytes, bytes, bytes, Optional[bytes]]:
    if args.vector:
        vector = VECTORS[args.vector]
        if args.operation != vector.operation:
            raise ValueError("--operation must match the selected --vector")
        return vector.a, vector.b, vector.value, vector.expected
    return args.a, args.b, args.value, None


def _physical_transport(port: str, baud: int, timeout: float) -> ByteTransport:
    try:
        import serial  # type: ignore
    except ImportError as error:
        raise MinCoreError("physical mode requires pyserial; install it with: python3 -m pip install pyserial") from error
    try:
        return serial.Serial(port=port, baudrate=baud, timeout=min(timeout, 0.1), write_timeout=timeout)
    except Exception as error:
        # Do not expose a potentially identifying serial device name in output.
        raise MinCoreError("could not open the requested serial port") from error


def _open_evidence(path: Optional[Path]) -> Optional[BinaryIO]:
    """Opened before any byte is sent so an unusable destination fails first."""
    if path is None:
        return None
    try:
        return path.open("ab")
    except OSError as error:
        raise MinCoreError(f"could not open the evidence destination: {error.strerror}") from error


def _record_failed_attempt(
    evidence: Optional[BinaryIO],
    *,
    provenance: tuple[str, Optional[bool]],
    operation: str,
    request: bytes,
    response: bytes,
    expected: Optional[bytes],
    failure: str,
    include_payloads: bool,
) -> None:
    """Note a device-touching attempt that never produced a validated response.

    Without it a run that opened the port, sent bytes, and then timed out is
    indistinguishable in the JSONL from one that never ran, even though the
    device may already have changed state.  `response` holds the bytes that did
    arrive before the failure, so a rejected or partial answer is not recorded
    as silence.  A secondary write error here must not replace the transport
    error the caller is about to raise.
    """
    if evidence is None:
        return
    try:
        record_evidence(
            evidence, provenance=provenance, operation=operation, request=request,
            response=response, expected=expected, passed=None, execution_attempted=True,
            serial_response_observed=bool(response), failure=failure,
            include_payloads=include_payloads,
        )
    except OSError:
        pass


def _close_quietly(resource: object) -> None:
    """Teardown runs in a finally block and must never mask the primary error."""
    close = getattr(resource, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Versioned MinCore raw-byte diagnostic transport (not LSC-1).")
    parser.add_argument("--port", help="explicit serial port; never enumerated or recorded")
    parser.add_argument("--baud", type=_baud_arg, default=115200)
    parser.add_argument("--timeout", type=_positive_finite, default=1.0)
    parser.add_argument("--operation", choices=("set", "xor", "mul", "status", "clear"), default="set")
    parser.add_argument("--vector", choices=tuple(VECTORS), help="hardcoded independent golden vector")
    parser.add_argument("--a", type=_hex_arg, default=b"")
    parser.add_argument("--b", type=_hex_arg, default=b"")
    parser.add_argument("--value", type=_hex_arg, default=b"")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="encode and report; default unless --execute")
    modes.add_argument("--encode", action="store_true", help="encode request only")
    modes.add_argument("--decode", type=_hex_arg, metavar="RESPONSE_HEX", help="validate a supplied response only")
    parser.add_argument("--execute", action="store_true", help="allow a serial transaction exactly once")
    parser.add_argument("--evidence", type=Path, help="append redacted JSONL evidence")
    parser.add_argument("--evidence-payloads", action="store_true",
                        help="include raw request/response payloads in evidence (may be sensitive)")
    args = parser.parse_args(argv)
    if args.execute and not args.port:
        parser.error("--execute requires explicit --port")
    if args.port and not args.execute:
        parser.error("--port is permitted only with --execute")
    if args.execute and (args.encode or args.decode is not None or args.dry_run):
        parser.error("--execute cannot be combined with --dry-run, --encode, or --decode")
    try:
        provenance = repo_provenance(args.evidence)
        a, b, value, expected = _operation_inputs(args)
        evidence = _open_evidence(args.evidence)
        try:
            if args.decode is not None:
                request = b""
                response = decode_response(args.operation, args.decode)
                passed = None if expected is None else response == expected
                execution_attempted, serial_response_observed = False, False
            elif args.execute:
                request = encode_request(args.operation, a=a, b=b, value=value)
                transport = _physical_transport(args.port, args.baud, args.timeout)
                # The port is open, so any later failure already touched the device.
                execution_attempted, serial_response_observed = True, False
                try:
                    request, response = MinCoreDriver(transport, args.timeout).exchange(args.operation, a=a, b=b, value=value)
                except MinCoreError as error:
                    _record_failed_attempt(
                        evidence, provenance=provenance, operation=args.operation,
                        request=request, response=error.observed, expected=expected,
                        failure=type(error).__name__,
                        include_payloads=args.evidence_payloads,
                    )
                    raise
                finally:
                    _close_quietly(transport)
                passed = None if expected is None else response == expected
                serial_response_observed = bool(response)
            else:
                request = encode_request(args.operation, a=a, b=b, value=value)
                response, passed = b"", None
                execution_attempted, serial_response_observed = False, False
            if evidence is not None:
                try:
                    record_evidence(
                        evidence, provenance=provenance,
                        operation=args.operation, request=request, response=response,
                        expected=expected, passed=passed, execution_attempted=execution_attempted,
                        serial_response_observed=serial_response_observed,
                        include_payloads=args.evidence_payloads,
                    )
                    evidence.close()
                except OSError as error:
                    raise MinCoreError(f"could not write the evidence record: {error.strerror}") from error
        finally:
            _close_quietly(evidence)
        print(json.dumps({"operation": args.operation, "request_hex": request.hex(),
                          "response_hex": response.hex(),
                          "expected_hex": None if expected is None else expected.hex(),
                          "pass": passed, "execution_attempted": execution_attempted,
                          "serial_response_observed": serial_response_observed}, sort_keys=True))
        return 0 if passed is not False else 1
    except (MinCoreError, ResponseError, ValueError) as error:
        print(f"mincore-uart: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

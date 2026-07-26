#!/usr/bin/env python3
"""
ULX3S UART harness driver (NEW path under fpga_harness/).

Explicit serial path only. No enumeration, no persistence, no auto-detect.
Opens a provided device path (e.g. /dev/ttyUSB0 or /dev/cu.usbserial-*) at 1 Mbaud 8N1.

Protocol: exact lean_silicon_lsc1 / MinCore byte stream:
  0x03 SET128  : 16 bytes payload -> 16 bytes echo
  0x01 XOR128  : 32 bytes (A,B interleaved) -> 16 bytes
  0x02 MUL128  : 32 bytes (A then B) -> 16 bytes

Every byte crosses the 8-bit ready/valid boundary. This driver only speaks bytes.

Usage (explicit path). --tx takes the command name, not the opcode byte:
  python3 -m fpga_harness.ulx3s_uart --port /dev/ttyUSB0 --tx status
  python3 -m fpga_harness.ulx3s_uart --port /dev/ttyUSB0 --tx set --payload 000102030405060708090a0b0c0d0e0f
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

# Deferred so the response-checking logic below can be imported and unit-tested
# on a machine with no pyserial and no board attached.
try:
    import serial  # pyserial
except ImportError:  # pragma: no cover - only hit without pyserial installed
    serial = None  # type: ignore[assignment]

# The GF(2^128) oracle lives in sim/, one level up from this package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sim.model import (  # noqa: E402
    gf_mul_bitserial,
    gf_mul_polynomial,
    int_to_le_bytes,
    le_bytes_to_int,
)

BAUD = 1_000_000
TIMEOUT_S = 2.0


def open_port(path: str, baud: int = BAUD, timeout: float = TIMEOUT_S) -> serial.Serial:
    """Open with explicit path. Caller owns lifetime."""
    if serial is None:
        raise RuntimeError("pyserial is required to reach a board; pip install pyserial")
    ser = serial.Serial(
        port=path,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=timeout,
        write_timeout=timeout,
        rtscts=False,
        dsrdtr=False,
        xonxoff=False,
    )
    try:
        ser.setDTR(False)
        ser.setRTS(False)
    except Exception:
        pass
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    time.sleep(0.05)
    return ser


def drain(ser: serial.Serial, max_bytes: int = 256) -> bytes:
    """Drain up to N stale bytes; used between transactions and after reset."""
    out = bytearray()
    deadline = time.time() + 0.05
    while len(out) < max_bytes and time.time() < deadline:
        waiting = ser.in_waiting
        if not waiting:
            time.sleep(0.001)
            continue
        out.extend(ser.read(min(waiting, max_bytes - len(out))))
    return bytes(out)


def send_bytes(ser: serial.Serial, data: bytes, inter_byte_delay: float = 0.0) -> None:
    for b in data:
        ser.write(bytes([b]))
        if inter_byte_delay > 0:
            time.sleep(inter_byte_delay)
    ser.flush()


def recv_exact(ser: serial.Serial, n: int, timeout: float = TIMEOUT_S) -> bytes:
    """Read exactly n bytes or raise once `timeout` seconds have passed.

    The port's own timeout is re-armed to the time actually left before each
    read. Leaving it at the value set in open_port bounds each read separately
    rather than the call as a whole, so a byte landing just before the deadline
    buys the read after it a whole fresh timeout: a 2 s budget takes nearly 4 s,
    and a dribbling link stretches it further still.
    """
    buf = bytearray()
    deadline = time.time() + timeout
    restore = getattr(ser, "timeout", None)
    try:
        while len(buf) < n:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            ser.timeout = remaining
            chunk = ser.read(n - len(buf))
            if chunk:
                buf.extend(chunk)
            else:
                time.sleep(max(0.0, min(0.0005, deadline - time.time())))
    finally:
        if restore is not None:
            ser.timeout = restore
    if len(buf) != n:
        raise TimeoutError(f"expected {n} bytes, got {len(buf)}")
    return bytes(buf)


# MinCore constants for independent oracle
SET128 = 0x03
XOR128 = 0x01
MUL128 = 0x02
CLEAR  = 0x7d
STATUS = 0x7e
ABORT  = 0x7f

# Fixed reply of status_byte() in asic_core/rtl/leanvm_b_stream_alu.sv:
# protocol major, protocol minor, opcode bitmap (XOR|MUL|SET|NONZERO), lane width.
STATUS_SIGNATURE = bytes([0x01, 0x01, 0x0F, 0x08])


def expected_mul(a: bytes, b: bytes) -> bytes:
    """Expected GF(2^128) product of two little-endian 16-byte operands.

    Computed by both oracles in sim.model and cross-checked. They share no
    intermediate steps: one is schoolbook carry-less multiply plus long
    reduction, the other is the LSB-first bit-serial recurrence the RTL uses.
    A disagreement means the oracle itself is broken, which must not be
    reported as a board failure.
    """
    if len(a) != 16 or len(b) != 16:
        raise ValueError("operands must be 16 bytes each")
    a_int = le_bytes_to_int(a)
    b_int = le_bytes_to_int(b)
    poly = gf_mul_polynomial(a_int, b_int)
    bitserial = gf_mul_bitserial(a_int, b_int)
    if poly != bitserial:
        raise AssertionError(
            f"GF(2^128) oracles disagree: {poly:032x} vs {bitserial:032x}"
        )
    return int_to_le_bytes(poly, 16)


def resync(ser: serial.Serial) -> None:
    """Abort any partial prior command before beginning a new transaction."""
    drain(ser)
    send_bytes(ser, bytes([ABORT]))


def reject_abort_byte(label: str, data: bytes) -> None:
    """Refuse operands the bridge cannot carry intact.

    fpga/ulx3s/uart_bridge.sv raises its abort pulse on *any* received 0x7f,
    including one that lands inside an operand, so the transaction is torn down
    mid-flight and the core answers 0xe0 for the remaining bytes. A 128-bit
    operand is arbitrary data, so this is reachable by ordinary vectors. Failing
    here keeps a transport limitation from being reported as a wrong product.
    """
    offsets = [i for i, b in enumerate(data) if b == ABORT]
    if offsets:
        raise ValueError(
            f"{label} contains the abort byte 0x{ABORT:02x} at offset(s) "
            f"{', '.join(str(i) for i in offsets)}; the UART bridge treats it as "
            f"an abort, so this operand cannot cross the link intact"
        )


def tx_set(ser: serial.Serial, value: bytes, timeout: float = TIMEOUT_S) -> bytes:
    assert len(value) == 16
    reject_abort_byte("SET128 value", value)
    resync(ser)
    send_bytes(ser, bytes([SET128]) + value)
    echo = recv_exact(ser, 16, timeout=timeout)
    return echo


def tx_xor(
    ser: serial.Serial, a: bytes, b: bytes, timeout: float = TIMEOUT_S
) -> bytes:
    assert len(a) == 16 and len(b) == 16
    reject_abort_byte("XOR128 operand A", a)
    reject_abort_byte("XOR128 operand B", b)
    resync(ser)
    pkt = bytes([XOR128])
    for i in range(16):
        pkt += bytes([a[i], b[i]])
    send_bytes(ser, pkt)
    res = recv_exact(ser, 16, timeout=timeout)
    return res


def tx_mul(
    ser: serial.Serial, a: bytes, b: bytes, timeout: float = TIMEOUT_S
) -> bytes:
    assert len(a) == 16 and len(b) == 16
    reject_abort_byte("MUL128 operand A", a)
    reject_abort_byte("MUL128 operand B", b)
    resync(ser)
    send_bytes(ser, bytes([MUL128]) + a + b)
    res = recv_exact(ser, 16, timeout=timeout)
    return res


def tx_clear(ser: serial.Serial) -> None:
    resync(ser)
    send_bytes(ser, bytes([CLEAR]))


def tx_status(ser: serial.Serial, timeout: float = TIMEOUT_S) -> bytes:
    resync(ser)
    send_bytes(ser, bytes([STATUS]))
    return recv_exact(ser, 4, timeout=timeout)


# Payload width each command consumes, in bytes. Single source of truth for the
# CLI validation below and for the usage examples the docs advertise.
PAYLOAD_BYTES = {"set": 16, "xor": 32, "mul": 32, "status": 0, "clear": 0}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="ULX3S UART driver for LSC-1 MinCore smoke")
    ap.add_argument("--port", required=True, help="Explicit serial device, e.g. /dev/ttyUSB0 or /dev/cu.usbserial-XXXX")
    ap.add_argument("--tx", choices=sorted(PAYLOAD_BYTES), default="status")
    ap.add_argument("--payload", default="", help="hex payload (for set: 32 hex chars; xor/mul: 64 hex chars)")
    ap.add_argument("--timeout", type=float, default=TIMEOUT_S)
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    port_path = args.port
    try:
        ser = open_port(port_path, timeout=args.timeout)
    except Exception as e:
        print(f"ERROR: cannot open {port_path}: {e}", file=sys.stderr)
        return 2

    try:
        stale = drain(ser)
        if stale:
            print(f"drained {len(stale)} stale bytes at open", file=sys.stderr)

        if args.tx == "clear":
            tx_clear(ser)
            print("CLEAR sent")
            return 0

        if args.tx == "status":
            st = tx_status(ser, timeout=args.timeout)
            print("STATUS:", st.hex())
            print("STATUS exp:", STATUS_SIGNATURE.hex())
            ok = st == STATUS_SIGNATURE
            print("MATCH:", ok)
            return 0 if ok else 1

        if not args.payload:
            print("ERROR: --payload required for set/xor/mul", file=sys.stderr)
            return 2
        try:
            pay = bytes.fromhex(args.payload)
        except ValueError:
            print("ERROR: payload must be hex", file=sys.stderr)
            return 2

        want = PAYLOAD_BYTES[args.tx]
        if len(pay) != want:
            print(
                f"ERROR: {args.tx} expects {want} bytes ({want * 2} hex chars)",
                file=sys.stderr,
            )
            return 2

        if args.tx == "set":
            echo = tx_set(ser, pay, timeout=args.timeout)
            print("SET echo:", echo.hex())
            ok = echo == pay
            print("MATCH:", ok)
            return 0 if ok else 1

        if args.tx == "xor":
            a, b = pay[:16], pay[16:]
            res = tx_xor(ser, a, b, timeout=args.timeout)
            exp = bytes(x ^ y for x, y in zip(a, b))
            print("XOR res :", res.hex())
            print("XOR exp :", exp.hex())
            print("MATCH:", res == exp)
            return 0 if res == exp else 1

        if args.tx == "mul":
            a, b = pay[:16], pay[16:]
            res = tx_mul(ser, a, b, timeout=args.timeout)
            exp = expected_mul(a, b)
            print("MUL res :", res.hex())
            print("MUL exp :", exp.hex())
            ok = res == exp
            print("MATCH:", ok)
            return 0 if ok else 1

        return 0
    except ValueError as e:
        # A payload the link cannot carry is a tooling limit, not a bad board,
        # so it must not share exit 1 with a genuine mismatch.
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    finally:
        try:
            ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())

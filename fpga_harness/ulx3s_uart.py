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

Usage (explicit path):
  python3 -m fpga_harness.ulx3s_uart --port /dev/ttyUSB0 --tx 03 --payload $(python3 -c 'print("00"*16)')
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

import serial  # pyserial

BAUD = 1_000_000
TIMEOUT_S = 2.0


def open_port(path: str, baud: int = BAUD, timeout: float = TIMEOUT_S) -> serial.Serial:
    """Open with explicit path. Caller owns lifetime."""
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
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            out.extend(chunk)
        else:
            time.sleep(0.001)
    return bytes(out)


def send_bytes(ser: serial.Serial, data: bytes, inter_byte_delay: float = 0.0) -> None:
    for b in data:
        ser.write(bytes([b]))
        if inter_byte_delay > 0:
            time.sleep(inter_byte_delay)
    ser.flush()


def recv_exact(ser: serial.Serial, n: int, timeout: float = TIMEOUT_S) -> bytes:
    """Read exactly n bytes or raise on timeout."""
    buf = bytearray()
    deadline = time.time() + timeout
    while len(buf) < n and time.time() < deadline:
        chunk = ser.read(n - len(buf))
        if chunk:
            buf.extend(chunk)
        else:
            time.sleep(0.0005)
    if len(buf) != n:
        raise TimeoutError(f"expected {n} bytes, got {len(buf)}")
    return bytes(buf)


# MinCore constants for independent oracle
SET128 = 0x03
XOR128 = 0x01
MUL128 = 0x02
CLEAR  = 0x7d
STATUS = 0x7e


def tx_set(ser: serial.Serial, value: bytes) -> bytes:
    assert len(value) == 16
    drain(ser)
    send_bytes(ser, bytes([SET128]) + value)
    echo = recv_exact(ser, 16)
    return echo


def tx_xor(ser: serial.Serial, a: bytes, b: bytes) -> bytes:
    assert len(a) == 16 and len(b) == 16
    drain(ser)
    pkt = bytes([XOR128])
    for i in range(16):
        pkt += bytes([a[i], b[i]])
    send_bytes(ser, pkt)
    res = recv_exact(ser, 16)
    return res


def tx_mul(ser: serial.Serial, a: bytes, b: bytes) -> bytes:
    assert len(a) == 16 and len(b) == 16
    drain(ser)
    send_bytes(ser, bytes([MUL128]) + a + b)
    res = recv_exact(ser, 16)
    return res


def tx_clear(ser: serial.Serial) -> None:
    drain(ser)
    send_bytes(ser, bytes([CLEAR]))


def tx_status(ser: serial.Serial) -> bytes:
    drain(ser)
    send_bytes(ser, bytes([STATUS]))
    return recv_exact(ser, 4)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="ULX3S UART driver for LSC-1 MinCore smoke")
    ap.add_argument("--port", required=True, help="Explicit serial device, e.g. /dev/ttyUSB0 or /dev/cu.usbserial-XXXX")
    ap.add_argument("--tx", choices=["set", "xor", "mul", "status", "clear"], default="status")
    ap.add_argument("--payload", default="", help="hex payload (for set: 32 hex chars; xor/mul: 64 hex chars)")
    ap.add_argument("--timeout", type=float, default=TIMEOUT_S)
    args = ap.parse_args(argv)

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
            st = tx_status(ser)
            print("STATUS:", st.hex())
            return 0

        if not args.payload:
            print("ERROR: --payload required for set/xor/mul", file=sys.stderr)
            return 2
        try:
            pay = bytes.fromhex(args.payload)
        except ValueError:
            print("ERROR: payload must be hex", file=sys.stderr)
            return 2

        if args.tx == "set":
            if len(pay) != 16:
                print("ERROR: set expects 16 bytes (32 hex chars)", file=sys.stderr)
                return 2
            echo = tx_set(ser, pay)
            print("SET echo:", echo.hex())
            ok = echo == pay
            print("MATCH:", ok)
            return 0 if ok else 1

        if args.tx == "xor":
            if len(pay) != 32:
                print("ERROR: xor expects 32 bytes (64 hex chars)", file=sys.stderr)
                return 2
            a, b = pay[:16], pay[16:]
            res = tx_xor(ser, a, b)
            exp = bytes(x ^ y for x, y in zip(a, b))
            print("XOR res :", res.hex())
            print("XOR exp :", exp.hex())
            print("MATCH:", res == exp)
            return 0 if res == exp else 1

        if args.tx == "mul":
            if len(pay) != 32:
                print("ERROR: mul expects 32 bytes (64 hex chars)", file=sys.stderr)
                return 2
            a, b = pay[:16], pay[16:]
            res = tx_mul(ser, a, b)
            print("MUL res :", res.hex())
            print("MUL (no local expected; compare to oracle)")
            return 0

        return 0
    finally:
        try:
            ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())

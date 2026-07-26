#!/usr/bin/env python3
"""Create a non-programming ULX3S host-preflight evidence record.

This command deliberately has no bitstream argument and never invokes a loader
with a programming or flash option.  Its only JTAG operation is the bounded
``openFPGALoader -b ulx3s --detect`` scan.  On Linux it prefers the stable FTDI
by-id name containing the documented ULX3S serial ``D01623`` and only then
falls back to a bounded, sorted ``/dev/ttyUSB*`` list.  A candidate UART is
opened and closed in a short-lived child process; no bytes, BREAK, DTR/RTS
change, flush, or drain operation is performed.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

try:
    from . import board_detect
except ImportError:  # direct script execution
    import board_detect  # type: ignore[no-redef]

FTDI_SERIAL = "D01623"
DEFAULT_TIMEOUT_S = 5.0
FORBIDDEN_LOADER_OPTIONS = ("-f", "--flash", "--write-flash", "--persistent")
_SECRET = re.compile(r"(?i)(token|password|secret|authorization)\s*([:=])\s*\S+")


def redact(value: str) -> str:
    return _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", value)


def bounded(command: Sequence[str], timeout: float) -> tuple[int | None, str]:
    """Run a non-interactive command under one wall-clock deadline."""
    try:
        run = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return None, redact((exc.stdout or "") + (exc.stderr or "") + "\nTIMEOUT")
    except OSError as exc:
        return None, redact(f"EXEC-ERROR: {exc}")
    return run.returncode, redact(f"{run.stdout}{run.stderr}")


def serial_candidates(
    platform_name: str = sys.platform,
    by_id: Path = Path("/dev/serial/by-id"),
    tty_glob: str = "/dev/ttyUSB*",
    globber: Callable[[str], list[str]] = glob.glob,
) -> list[str]:
    """Return stable names first; no device is opened while discovering."""
    if platform_name == "linux":
        stable = sorted(str(p) for p in by_id.glob("*") if FTDI_SERIAL in p.name)
        return stable or sorted(globber(tty_glob))[:8]
    if platform_name == "darwin":
        return sorted(globber("/dev/cu.usbserial-*") + globber("/dev/tty.usbserial-*"))[:8]
    return []


def device_metadata(path: str) -> dict[str, object]:
    try:
        info = os.stat(path)
    except OSError as exc:
        return {"path": path, "error": str(exc)}
    return {
        "path": path,
        "mode": stat.filemode(info.st_mode),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "readable": os.access(path, os.R_OK),
        "writable": os.access(path, os.W_OK),
    }


def _serial_probe_command(path: str, timeout: float) -> list[str]:
    code = (
        "import serial,sys; "
        f"s=serial.Serial(sys.argv[1], baudrate=1000000, timeout={timeout!r}, write_timeout={timeout!r}); "
        "s.close(); print('opened-and-closed')"
    )
    return [sys.executable, "-c", code, path]


def safe_loader_detect(timeout: float) -> dict[str, object]:
    loader = shutil.which("openFPGALoader")
    command = [loader, "-b", "ulx3s", "--detect"] if loader else ["openFPGALoader", "-b", "ulx3s", "--detect"]
    # Keep the invariant local and testable if this code is ever refactored.
    if any(option in command for option in FORBIDDEN_LOADER_OPTIONS):
        raise RuntimeError("unsafe loader option refused")
    rc, output = bounded(command, timeout)
    code = board_detect._recognised_idcode(output)
    return {
        "command": command,
        "timeout_seconds": timeout,
        "returncode": rc,
        "output": output,
        "idcode": f"0x{code:08x}" if code is not None else None,
        "model": board_detect.ECP5_IDCODES.get(code) if code is not None else None,
    }


def version(name: str) -> str | None:
    value = board_detect._tool_version(name)
    return value or None


def evidence(timeout: float, check_uart: bool = True) -> dict[str, object]:
    """Collect safe observations.  This function never writes protocol bytes."""
    candidates = serial_candidates()
    uart: dict[str, object] = {"candidates": [device_metadata(p) for p in candidates]}
    if check_uart and candidates:
        path = candidates[0]
        command = _serial_probe_command(path, timeout)
        rc, output = bounded(command, timeout)
        uart["open_close"] = {
            "path": path, "command": command, "timeout_seconds": timeout,
            "returncode": rc, "output": output,
            "protocol_writes": False, "break_sent": False,
        }
    elif check_uart:
        uart["open_close"] = {"skipped": "no serial candidate; loader released before UART probe"}
    usb = [
        {"vid": f"0x{vid:04x}", "pid": f"0x{pid:04x}", "label": label}
        for vid, pid, label in board_detect._enumerate_usb()
    ]
    return {
        "schema": "lean-silicon.ulx3s-preflight.v1",
        "safety": {"programming": False, "flash": False, "protocol_writes": False, "break": False},
        "host_boundary": {"platform": sys.platform, "uname": platform.uname()._asdict(), "euid": os.geteuid()},
        "git": {"commit": _git(["rev-parse", "HEAD"]), "clean": _git(["status", "--porcelain"]) == ""},
        "tools": {name: version(name) for name in ("yosys", "nextpnr-ecp5", "ecppack", "openFPGALoader")},
        "python": {"version": sys.version.split()[0], "pyserial": _pyserial_version()},
        "usb": usb,
        "jtag": safe_loader_detect(timeout),
        "uart": uart,
    }


def _git(arguments: Sequence[str]) -> str | None:
    rc, output = bounded(["git", *arguments], 2.0)
    return output.strip() if rc == 0 else None


def _pyserial_version() -> str | None:
    try:
        import serial
        return str(serial.__version__)
    except ImportError:
        return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, help="write JSON evidence to this new file")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--no-uart-open", action="store_true", help="do not open/close a discovered UART")
    args, unknown = parser.parse_known_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if any(arg in FORBIDDEN_LOADER_OPTIONS or "flash" in arg.lower() for arg in unknown):
        parser.error("programming and persistent-flash options are refused")
    if unknown:
        parser.error(f"unknown arguments: {' '.join(unknown)}")
    payload = evidence(args.timeout, check_uart=not args.no_uart_open)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        if args.output.exists():
            print("refusing to overwrite existing evidence file", file=sys.stderr)
            return 2
        args.output.write_text(encoded)
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

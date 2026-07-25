#!/usr/bin/env python3
"""Layered ULX3S/ECP5 detection that never upgrades visibility into validation.

The four levels are deliberately separate because each answers a strictly
weaker question than the next:

  toolchain  a build/load program exists on this machine
  usb        something claiming the ULX3S USB identity is enumerated
  jtag       an ECP5 TAP answers with a recognised IDCODE
  datapath   host bytes actually crossed the exact LSC-1 8-bit ready/valid
             pins and produced the expected response bytes

Only ``datapath`` is evidence that the harness works.  This tool can never
report it as satisfied: the repository contains no harness bitstream and no
recorded byte-exchange log, so there is nothing to validate against.  Raising
that level requires real hardware logs committed by a later change, not a
different exit code here.

The ``usb`` and ``jtag`` probes are host-specific: Linux has sysfs, macOS has
the IOKit registry, and ``openFPGALoader --detect`` has to be told the ULX3S
board profile before it will talk to an FT231X.  Getting either wrong reports
an attached board as absent, which is a detection bug, not evidence about the
fabric.

Every probe is injected through :class:`Environment`, so the whole ladder is
reproducible from a JSON fixture with no board, no USB, and no toolchain.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence
from xml.parsers.expat import ExpatError

LEVELS = ("toolchain", "usb", "jtag", "datapath")

# Vendor-documented identifiers. Unconfirmed against physical hardware in this
# repository; see BUILD_PLAN.md for the unknowns this leaves open.
ULX3S_USB_VID = 0x0403
ULX3S_USB_PID = 0x6015
ECP5_IDCODES: Mapping[int, str] = {
    0x21111043: "LFE5U-12F",
    0x41111043: "LFE5U-25F",
    0x41112043: "LFE5U-45F",
    0x41113043: "LFE5U-85F",
}

BUILD_TOOLS = ("yosys", "nextpnr-ecp5", "ecppack")
LOAD_TOOLS = ("openFPGALoader", "fujprog")

# Prerequisites that do not exist in this repository. Listed so the datapath
# verdict names what is missing instead of only refusing.
DATAPATH_PREREQUISITES = (
    "a synthesised ULX3S bitstream for a harness top-level",
    "an ECP5 pin constraint file (.lpf) mapping the 8-bit interface to board pins",
    "a host-side byte-exchange driver for the ready/valid handshake",
    "a recorded request/response byte log captured from real hardware",
)

_IDCODE_RE = re.compile(r"0x([0-9a-fA-F]{8})")

SYSFS_USB_ROOT = Path("/sys/bus/usb/devices")

# macOS has no sysfs. `system_profiler SPUSBDataType` is not a reliable source
# either — it can return an empty device list on a machine where the board is
# plainly attached — so the IOKit registry is read directly instead.
IOREG_COMMAND = ("ioreg", "-p", "IOUSB", "-a", "-l")

# Only these keys are ever read out of the IOKit plist. `USB Serial Number` is
# a per-board identifier that would end up in reports and CI logs, so it is
# deliberately not in the allowlist and must never be added.
IOREG_VENDOR_KEY = "idVendor"
IOREG_PRODUCT_KEY = "idProduct"
IOREG_LABEL_KEYS = ("USB Product Name", "IORegistryEntryName")
IOREG_FORBIDDEN_KEYS = frozenset({"USB Serial Number", "kUSBSerialNumberString"})

# The registry is a tree of untrusted-shaped data; these bound the walk so a
# hostile or truncated plist cannot exhaust memory or the recursion limit.
IOREG_MAX_DEPTH = 64
IOREG_MAX_DEVICES = 512
USB_LABEL_MAX_LEN = 64

# openFPGALoader's own `--detect` assumes an FT2232 cable, which is not what a
# ULX3S carries; the board profile has to be named first. The bare form is kept
# as a fallback so an external JTAG cable still works.
JTAG_DETECT_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("-b", "ulx3s", "--detect"),
    ("--detect",),
)

# openFPGALoader 1.1.1 spells this with a capital V and rejects `--version`.
# Older builds only accept the lowercase form, so both are tried in order.
VERSION_FLAGS: Mapping[str, tuple[str, ...]] = {
    "openFPGALoader": ("--Version", "--version"),
}
DEFAULT_VERSION_FLAGS = ("--version",)
VERSION_MAX_LEN = 120
VERSION_SCAN_LINES = 5

# Substrings that mean the tool rejected the flag rather than answering it.
# Without this, an option-parser complaint gets reported as a version string.
VERSION_REJECT_MARKERS = (
    "unrecognized option",
    "unrecognised option",
    "unknown option",
    "invalid option",
    "no such option",
    "not expected",
    "usage:",
    "error:",
    "try --help",
    "run with --help",
    "for more information",
)


@dataclass(frozen=True)
class Finding:
    level: str
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class Report:
    findings: tuple[Finding, ...]

    def satisfied(self, level: str) -> bool:
        """A level holds only when it has at least one finding and none failed."""
        relevant = [item for item in self.findings if item.level == level]
        return bool(relevant) and all(item.status == "present" for item in relevant)

    @property
    def highest_satisfied(self) -> str | None:
        reached = None
        for level in LEVELS:
            if not self.satisfied(level):
                break
            reached = level
        return reached

    @property
    def datapath_validated(self) -> bool:
        return self.satisfied("datapath")

    def as_dict(self) -> dict[str, object]:
        return {
            "levels": list(LEVELS),
            "findings": [item.as_dict() for item in self.findings],
            "satisfied": {level: self.satisfied(level) for level in LEVELS},
            "highest_satisfied_level": self.highest_satisfied,
            "datapath_validated": self.datapath_validated,
            "verdict": (
                "data-path behaviour is NOT validated; "
                "lower levels only prove tool, USB, or JTAG visibility"
            ),
        }


@dataclass
class Environment:
    """Injectable probe surface. Defaults answer 'nothing is here'."""

    which: Callable[[str], str | None] = lambda _name: None
    version: Callable[[str], str] = lambda _name: ""
    usb_devices: Callable[[], Sequence[tuple[int, int, str]]] = tuple
    jtag_scan: Callable[[], str] = str

    @classmethod
    def from_fixture(cls, fixture: Mapping[str, object]) -> "Environment":
        """Build a deterministic environment from plain JSON-shaped data."""
        tools = {
            str(name): str(value)
            for name, value in dict(fixture.get("tools") or {}).items()
        }
        versions = {
            str(name): str(value)
            for name, value in dict(fixture.get("versions") or {}).items()
        }
        devices = tuple(
            (int(entry[0]), int(entry[1]), str(entry[2]))
            for entry in (fixture.get("usb_devices") or ())
        )
        scan = str(fixture.get("jtag_scan") or "")
        return cls(
            which=tools.get,
            version=lambda name: versions.get(name, ""),
            usb_devices=lambda: devices,
            jtag_scan=lambda: scan,
        )

    @classmethod
    def real(cls) -> "Environment":
        return cls(
            which=shutil.which,
            version=_tool_version,
            usb_devices=_enumerate_usb,
            jtag_scan=_jtag_scan,
        )


def _capture(command: Sequence[str]) -> str:
    try:
        finished = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return f"{finished.stdout}\n{finished.stderr}"


def _capture_bytes(command: Sequence[str]) -> bytes:
    """Raw stdout only. stderr is dropped so it cannot corrupt a plist body."""
    try:
        finished = subprocess.run(
            list(command),
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return b""
    return finished.stdout or b""


def _looks_like_parser_complaint(line: str) -> bool:
    lowered = line.lower()
    return any(marker in lowered for marker in VERSION_REJECT_MARKERS)


def _first_version_line(text: str) -> str:
    """First plausible version line, or empty if the flag was rejected.

    A tool that does not know the flag still prints something, so the output is
    only accepted when it neither reads as an option-parser complaint nor lacks
    a digit.  Otherwise ``openFPGALoader: unknown option`` becomes a version.
    """
    for raw in text.splitlines()[:VERSION_SCAN_LINES]:
        line = raw.strip()
        if not line:
            continue
        if _looks_like_parser_complaint(line):
            return ""
        if any(char.isdigit() for char in line):
            return line[:VERSION_MAX_LEN]
    return ""


def _tool_version(
    name: str,
    capture: Callable[[Sequence[str]], str] = _capture,
) -> str:
    path = shutil.which(name)
    if path is None:
        return ""
    for flag in VERSION_FLAGS.get(name, DEFAULT_VERSION_FLAGS):
        version = _first_version_line(capture([path, flag]))
        if version:
            return version
    return ""


def _usb_label(value: object) -> str:
    if not isinstance(value, str):
        return ""
    printable = "".join(char for char in value if char.isprintable())
    return printable.strip()[:USB_LABEL_MAX_LEN]


def _usb_identifier(value: object) -> int | None:
    """USB ids are 16-bit integers; anything else is not one (bools included)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 0xFFFF else None


def _ioreg_device(node: Mapping[object, object]) -> tuple[int, int, str] | None:
    vid = _usb_identifier(node.get(IOREG_VENDOR_KEY))
    pid = _usb_identifier(node.get(IOREG_PRODUCT_KEY))
    if vid is None or pid is None:
        return None
    label = ""
    for key in IOREG_LABEL_KEYS:
        label = _usb_label(node.get(key))
        if label:
            break
    return (vid, pid, label or f"{vid:#06x}:{pid:#06x}")


def _walk_ioreg(node: object, devices: list[tuple[int, int, str]], depth: int) -> None:
    """Collect USB identities from the IOKit tree, ignoring every other key."""
    if depth > IOREG_MAX_DEPTH or len(devices) >= IOREG_MAX_DEVICES:
        return
    if isinstance(node, list):
        for child in node:
            _walk_ioreg(child, devices, depth + 1)
        return
    if not isinstance(node, dict):
        return
    device = _ioreg_device(node)
    if device is not None:
        devices.append(device)
    for value in node.values():
        if isinstance(value, (list, dict)):
            _walk_ioreg(value, devices, depth + 1)


def _enumerate_usb_ioreg(
    capture: Callable[[Sequence[str]], bytes] = _capture_bytes,
) -> tuple[tuple[int, int, str], ...]:
    """Read USB identities from the macOS IOKit registry.

    A missing, truncated, or otherwise unparseable plist is indistinguishable
    from 'no board here' for detection purposes, so it yields an empty tuple
    rather than an exception.
    """
    raw = capture(list(IOREG_COMMAND))
    if not raw:
        return ()
    try:
        parsed = plistlib.loads(raw)
    except (ValueError, ExpatError, TypeError, OverflowError, RecursionError):
        return ()
    devices: list[tuple[int, int, str]] = []
    _walk_ioreg(parsed, devices, 0)
    return tuple(devices)


def _enumerate_usb() -> tuple[tuple[int, int, str], ...]:
    if sys.platform == "darwin":
        return _enumerate_usb_ioreg()
    return _enumerate_usb_sysfs()


def _enumerate_usb_sysfs(
    root: Path = SYSFS_USB_ROOT,
) -> tuple[tuple[int, int, str], ...]:
    """Read USB identities from sysfs; absent or unreadable means empty."""
    if not root.is_dir():
        return ()
    devices: list[tuple[int, int, str]] = []
    for entry in sorted(root.iterdir()):
        vendor = entry / "idVendor"
        product = entry / "idProduct"
        if not (vendor.is_file() and product.is_file()):
            continue
        try:
            vid = int(vendor.read_text().strip(), 16)
            pid = int(product.read_text().strip(), 16)
        except (OSError, ValueError):
            continue
        label = entry / "product"
        try:
            name = label.read_text().strip() if label.is_file() else entry.name
        except OSError:
            name = entry.name
        devices.append((vid, pid, name))
    return tuple(devices)


def _recognised_idcode(output: str) -> int | None:
    for raw in _IDCODE_RE.findall(output):
        code = int(raw, 16)
        if code in ECP5_IDCODES:
            return code
    return None


def _jtag_scan(capture: Callable[[Sequence[str]], str] = _capture) -> str:
    """Scan with the ULX3S board profile first, then the bare form.

    Bare ``--detect`` assumes an FT2232 cable and fails on a ULX3S, whose FT231X
    needs ``-b ulx3s``.  The bare form is still tried when the profile answers
    with nothing recognised, so an external JTAG cable keeps working.
    """
    loader = shutil.which("openFPGALoader")
    if loader is None:
        return ""
    attempts: list[str] = []
    for arguments in JTAG_DETECT_COMMANDS:
        output = capture([loader, *arguments])
        if _recognised_idcode(output) is not None:
            return output
        attempts.append(output)
    return next((text for text in attempts if text.strip()), "")


def _probe_toolchain(env: Environment) -> list[Finding]:
    """Build tools are a chain, so all are required; loaders are alternatives."""
    findings: list[Finding] = []
    for group, tools, needs_all in (
        ("build", BUILD_TOOLS, True),
        ("load", LOAD_TOOLS, False),
    ):
        found = [name for name in tools if env.which(name)]
        missing = [name for name in tools if name not in found]
        if found and (not missing if needs_all else True):
            status = "present"
            detail = ", ".join(
                f"{name}={env.version(name) or env.which(name)}" for name in found
            )
        elif found:
            status = "absent"
            detail = (
                f"found {', '.join(found)} but missing {', '.join(missing)}; "
                f"the {' -> '.join(tools)} chain is incomplete"
            )
        else:
            status = "absent"
            detail = f"none of {', '.join(tools)} on PATH"
        findings.append(Finding("toolchain", f"{group}-tools", status, detail))
    return findings


def _probe_usb(env: Environment) -> list[Finding]:
    devices = tuple(env.usb_devices())
    matches = [
        entry
        for entry in devices
        if entry[0] == ULX3S_USB_VID and entry[1] == ULX3S_USB_PID
    ]
    if matches:
        names = ", ".join(name for _vid, _pid, name in matches)
        return [
            Finding(
                "usb",
                "ulx3s-usb-identity",
                "present",
                f"{len(matches)} device(s) matching "
                f"{ULX3S_USB_VID:#06x}:{ULX3S_USB_PID:#06x} ({names}); "
                "a USB identity is not fabric behaviour",
            )
        ]
    return [
        Finding(
            "usb",
            "ulx3s-usb-identity",
            "absent",
            f"no {ULX3S_USB_VID:#06x}:{ULX3S_USB_PID:#06x} among "
            f"{len(devices)} enumerated device(s)",
        )
    ]


def _probe_jtag(env: Environment) -> list[Finding]:
    output = env.jtag_scan()
    if not output.strip():
        return [
            Finding(
                "jtag",
                "ecp5-idcode",
                "absent",
                "no JTAG scan output (loader missing, or no chain answered)",
            )
        ]
    code = _recognised_idcode(output)
    if code is not None:
        return [
            Finding(
                "jtag",
                "ecp5-idcode",
                "present",
                f"IDCODE {code:#010x} identifies {ECP5_IDCODES[code]}; "
                "silicon identity only, says nothing about a loaded design",
            )
        ]
    return [
        Finding(
            "jtag",
            "ecp5-idcode",
            "absent",
            "scan output contained no recognised ECP5 IDCODE",
        )
    ]


def _probe_datapath(_env: Environment) -> list[Finding]:
    """Always unvalidated: there is nothing in-repo to validate against."""
    missing = "; ".join(DATAPATH_PREREQUISITES)
    return [
        Finding(
            "datapath",
            "byte-exchange-over-8bit-pins",
            "not-validated",
            f"no data-path evidence exists in this repository. Missing: {missing}",
        )
    ]


PROBES: Mapping[str, Callable[[Environment], list[Finding]]] = {
    "toolchain": _probe_toolchain,
    "usb": _probe_usb,
    "jtag": _probe_jtag,
    "datapath": _probe_datapath,
}


def detect(env: Environment) -> Report:
    findings: list[Finding] = []
    for level in LEVELS:
        findings.extend(PROBES[level](env))
    return Report(tuple(findings))


def render(report: Report) -> str:
    lines = ["LSC-1 ULX3S/ECP5 detection ladder"]
    for level in LEVELS:
        mark = "ok " if report.satisfied(level) else "-- "
        lines.append(f"  [{mark}] {level}")
        for item in report.findings:
            if item.level == level:
                lines.append(f"        {item.name}: {item.status} — {item.detail}")
    reached = report.highest_satisfied or "none"
    lines.append(f"  highest satisfied level: {reached}")
    lines.append(
        "  data-path behaviour validated: "
        f"{'yes' if report.datapath_validated else 'NO'}"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fixture",
        type=Path,
        help="JSON fixture describing tools/usb_devices/jtag_scan; "
        "omit to probe the real machine",
    )
    parser.add_argument(
        "--require",
        choices=("none", *LEVELS),
        default="none",
        help="exit non-zero unless this level is satisfied (default: none). "
        "'datapath' always fails until real hardware evidence exists",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    if args.fixture is not None:
        env = Environment.from_fixture(json.loads(args.fixture.read_text()))
    else:
        env = Environment.real()

    report = detect(env)
    print(json.dumps(report.as_dict(), indent=2) if args.json else render(report))

    if args.require == "none":
        return 0
    if report.satisfied(args.require):
        return 0
    print(f"required level not satisfied: {args.require}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

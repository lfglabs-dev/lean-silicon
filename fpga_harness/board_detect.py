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

Every probe is injected through :class:`Environment`, so the whole ladder is
reproducible from a JSON fixture with no board, no USB, and no toolchain.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

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


def _tool_version(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        return ""
    lines = _capture([path, "--version"]).strip().splitlines()
    return lines[0].strip() if lines else ""


def _enumerate_usb() -> tuple[tuple[int, int, str], ...]:
    """Read USB identities from sysfs; absent or unreadable means empty."""
    root = Path("/sys/bus/usb/devices")
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


def _jtag_scan() -> str:
    loader = shutil.which("openFPGALoader")
    if loader is None:
        return ""
    return _capture([loader, "--detect"])


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
    for raw in _IDCODE_RE.findall(output):
        code = int(raw, 16)
        if code in ECP5_IDCODES:
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

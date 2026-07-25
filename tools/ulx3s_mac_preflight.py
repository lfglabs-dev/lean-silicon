#!/usr/bin/env python3
"""macOS preflight capture for a physical ULX3S-85F over US1.

This is a *visibility* capture, not a validation.  It answers three questions
and nothing beyond them:

  cable/USB  does the Mac enumerate an FTDI bridge at the ULX3S USB identity?
  toolchain  which loader/build programs exist on this Mac, at which versions?
  jtag       does an ECP5 TAP answer ``openFPGALoader --detect`` with an IDCODE?

None of that is data-path evidence.  Bytes have not crossed the LSC-1 8-bit
ready/valid pins, and this tool cannot make them.  ``--next-stage`` prints the
command shape for that work and exits non-zero until its prerequisites exist.

Why this lives here and not in ``fpga_harness/board_detect.py``
--------------------------------------------------------------
``board_detect.py`` owns the four-level detection ladder and is owned by the
ULX3S harness lane.  Two of its probes are Linux-shaped and give false
negatives on macOS with a board attached and enumerating:

  ``_enumerate_usb``  reads ``/sys/bus/usb/devices``, which is Linux sysfs and
                      does not exist on macOS, so the ``usb`` level reads
                      absent.
  ``_jtag_scan``      runs a bare ``openFPGALoader --detect``, which exits 1 on
                      a ULX3S because the default cable is FT2232, so the
                      ``jtag`` level reads absent.

Neither is a board fault, and neither is fixed here: that file belongs to the
ULX3S harness lane.  ``docs/ULX3S_MAC_PREFLIGHT.md`` records both as follow-up
work owned by that lane.

Rather than change another lane's file, this tool captures both layers itself
(USB via ``system_profiler`` then ``ioreg``, JTAG with an explicit ``-b
ulx3s``) and emits a fixture in the exact shape ``board_detect.py`` already
documents for ``--fixture``.  The ladder is then replayed unmodified, on this
Mac or on any reviewer's machine:

    python3 tools/ulx3s_mac_preflight.py --out preflight.json \
        --fixture-out board.fixture.json
    python3 fpga_harness/board_detect.py --fixture board.fixture.json --json

Toolchain and JTAG captures keep their raw output, so a parse this tool gets
wrong is still reviewable from the artifact.  USB captures do not: a raw USB
enumeration lists everything plugged into the machine, serial numbers
included, so only a length and a SHA-256 are kept unless
``--include-usb-detail`` is passed.  The artifact is meant to be attachable to
a pull request.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import types
from xml.parsers.expat import ExpatError

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The harness lane owns the identity constants; import them, never restate.
_DETECT_SOURCE = ROOT / "fpga_harness" / "board_detect.py"
_detect = types.ModuleType("_tracked_board_detect")
_detect.__file__ = str(_DETECT_SOURCE)
sys.modules[_detect.__name__] = _detect
try:
    exec(compile(_DETECT_SOURCE.read_bytes(), str(_DETECT_SOURCE), "exec"), _detect.__dict__)
finally:
    del sys.modules[_detect.__name__]

ULX3S_USB_VID = _detect.ULX3S_USB_VID
ULX3S_USB_PID = _detect.ULX3S_USB_PID
ECP5_IDCODES = _detect.ECP5_IDCODES
IDCODE_RE = _detect._IDCODE_RE

SCHEMA = "leansilicon.hardware.preflight/1"

#: Raw captures are embedded verbatim up to this size, then marked truncated.
RAW_LIMIT = 64 * 1024

#: USB enumeration on Darwin, in order.  `system_profiler SPUSBDataType`
#: returned an empty tree on macOS 26.5.2 with a board attached and
#: enumerating, so it cannot be the only probe; `ioreg -p IOUSB` saw the same
#: board on the same host.  Every probe runs and every probe is recorded, and
#: the first one that yields devices is the one reported as the source.
USB_COMMANDS = (
    ("system_profiler", ("system_profiler", "SPUSBDataType", "-json")),
    ("ioreg-plist", ("ioreg", "-p", "IOUSB", "-a", "-l", "-w", "0")),
    ("ioreg-text", ("ioreg", "-p", "IOUSB", "-l", "-w", "0")),
)

#: openFPGALoader spells its version flag differently across releases, and
#: 1.1.1 rejects `--version` outright, so try each and record which answered.
VERSION_FLAGS = ("--Version", "-V", "--version")

#: A version string has to look like one; used only to salvage a tool that
#: prints its version and then exits non-zero.
VERSION_RE = re.compile(r"\d+\.\d+")

#: Redaction placeholder for values that must not reach the repository.
REDACTED = "<redacted>"

PROBED_TOOLS = (
    "openFPGALoader",
    "fujprog",
    "dfu-util",
    "yosys",
    "nextpnr-ecp5",
    "ecppack",
)

#: JTAG probes in order; the first that returns output wins, all are recorded.
#: The explicit `-b ulx3s` board profile comes first because openFPGALoader
#: defaults to an FT2232 cable and exits 1 on a ULX3S without it.
JTAG_COMMANDS = (
    ("openFPGALoader", "-b", "ulx3s", "--detect"),
    ("openFPGALoader", "-c", "ft232", "--detect"),
    ("openFPGALoader", "--detect"),
)

#: Physical facts no software probe on the Mac can establish.  Each is
#: `unconfirmed` until a human reads the board and passes --confirm.
CHECKLIST = (
    ("board_revision",
     "Which ULX3S board revision is this?",
     "Silkscreen on the PCB, near the ULX3S logo (for example 'v3.1.8'). "
     "Read the silkscreen, not the USB product string: on the board captured "
     "in results/ulx3s-hardware-preflight-macos-20260725 the descriptor says "
     "v3.0.8 while the PCB says v3.1.8, and the silkscreen is authoritative."),
    ("fpga_density",
     "Which ECP5 density is fitted?",
     "The marking on the large Lattice package, e.g. LFE5U-85F. "
     "Cross-check against the JTAG IDCODE captured in this artifact."),
    ("sdram_part",
     "What is the SDRAM part number and size?",
     "The marking on the SDRAM chip, e.g. AS4C16M16SB-6TIN (16Mx16 = 32 MiB). "
     "Recorded for inventory only; the LSC-1 harness must not use SDRAM."),
    ("us1_connector",
     "Is US1 a Micro-B connector on this revision?",
     "The USB connector nearest the FT231X, silkscreened US1."),
    ("cable_type",
     "Which cable is in use, and is it a data cable?",
     "A USB-C to Micro-B cable that carries data. Charge-only cables power the "
     "board (LEDs light) but enumerate nothing; see the failure signature in "
     "docs/ULX3S_MAC_PREFLIGHT.md."),
    ("power_source",
     "Is the board powered from US1 alone, or from an external supply?",
     "Jumper/switch position and whether anything else is plugged in."),
)

#: `--next-stage` refuses until each of these exists in the tree.  Wording is
#: kept aligned with fpga_harness/BUILD_PLAN.md stages 2-4.
NEXT_STAGE_PREREQUISITES = (
    ("lpf_constraints",
     "an ECP5 pin constraint file (.lpf) mapping all 24 interface signals",
     lambda root: sorted(str(p.relative_to(root)) for p in root.rglob("*.lpf"))),
    ("board_top",
     "a ULX3S board top that instantiates lean_silicon_lsc1",
     lambda root: sorted(
         str(path.relative_to(root))
         for path in (root / "fpga_harness" / "rtl").glob("*.sv")
         if "lean_silicon_lsc1 " in path.read_text()
         or "lean_silicon_lsc1 #" in path.read_text())),
    ("timing_clean_bitstream",
     "a bitstream with a passing 25 MHz timing report, not merely a build",
     lambda root: sorted(
         str(path.relative_to(root))
         for pattern in ("*.bit", "*.svf", "*timing*.rpt")
         for path in root.rglob(pattern))),
    ("host_byte_driver",
     "a host-side byte-exchange driver for the ready/valid handshake",
     lambda root: sorted(
         str(path.relative_to(root))
         for path in (root / "host").glob("*.py")
         if "serial" in path.read_text().lower() and "ULX3S" in path.read_text())),
)

#: Printed by --next-stage.  Never executed by this tool.
NEXT_STAGE_COMMANDS = (
    ("stage 2", "write fpga_harness/ulx3s.lpf and a board top, then:",
     "make fpga-boundary"),
    ("stage 3", "synthesise and check timing at 25 MHz before packing:",
     "yosys -p 'synth_ecp5 -top ulx3s_top -json build/ulx3s.json' <sources> && "
     "nextpnr-ecp5 --85k --json build/ulx3s.json --lpf fpga_harness/ulx3s.lpf "
     "--textcfg build/ulx3s.config --freq 25 --report build/timing.json && "
     "ecppack build/ulx3s.config build/ulx3s.bit"),
    ("stage 3", "load it, without claiming anything about behaviour:",
     "openFPGALoader -b ulx3s build/ulx3s.bit"),
    ("stage 4", "drive real bytes and record both directions:",
     "make ulx3s-byte-log LEANVM_B_UPSTREAM=/path/to/leanVM-b"),
)


def clip(text: str) -> tuple[str, bool]:
    return (text[:RAW_LIMIT], True) if len(text) > RAW_LIMIT else (text, False)


def run(command: tuple[str, ...] | list[str], timeout: int = 30) -> dict:
    """Run one probe and record it whether it works or not."""
    executable = shutil.which(command[0])
    if executable is None:
        return {"command": list(command), "found": False, "returncode": None,
                "stdout": "", "stderr": "", "truncated": False,
                "error": f"{command[0]} is not on PATH"}
    try:
        finished = subprocess.run(
            [executable, *command[1:]], capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"command": list(command), "found": True, "returncode": None,
                "stdout": "", "stderr": "", "truncated": False,
                "error": f"{type(error).__name__}: {error}"}
    stdout, stdout_clipped = clip(finished.stdout)
    stderr, stderr_clipped = clip(finished.stderr)
    return {
        "command": list(command),
        "found": True,
        "returncode": finished.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": stdout_clipped or stderr_clipped,
        "error": None,
    }


def parse_hex_field(value) -> int | None:
    """``"0x0403  (Future Technology Devices ...)"`` -> ``0x0403``."""
    if not isinstance(value, str):
        return None
    token = value.strip().split()[0] if value.strip() else ""
    try:
        return int(token, 16)
    except ValueError:
        return None


def walk_usb(nodes, out: list[dict]) -> None:
    """Flatten the nested ``SPUSBDataType`` tree; hubs carry ``_items``."""
    for node in nodes or ():
        if not isinstance(node, dict):
            continue
        vid = parse_hex_field(node.get("vendor_id"))
        pid = parse_hex_field(node.get("product_id"))
        if vid is not None and pid is not None:
            out.append({
                "name": node.get("_name"),
                "vendor_id": vid,
                "product_id": pid,
                "vendor_id_raw": node.get("vendor_id"),
                "product_id_raw": node.get("product_id"),
                "manufacturer": node.get("manufacturer"),
                "serial_num": node.get("serial_num"),
                "location_id": node.get("location_id"),
                "device_speed": node.get("device_speed"),
            })
        walk_usb(node.get("_items"), out)


def parse_usb(payload: str) -> tuple[list[dict], str | None]:
    """Parse ``system_profiler SPUSBDataType -json`` output."""
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        return [], f"system_profiler output is not JSON: {error}"
    devices: list[dict] = []
    walk_usb(document.get("SPUSBDataType"), devices)
    return devices, None


def walk_ioreg(nodes, out: list[dict]) -> None:
    """Flatten an ``ioreg -a -l`` plist tree; identities are plain integers."""
    for node in nodes or ():
        if not isinstance(node, dict):
            continue
        vid, pid = node.get("idVendor"), node.get("idProduct")
        if isinstance(vid, int) and isinstance(pid, int):
            out.append({
                "name": node.get("USB Product Name") or node.get("IORegistryEntryName"),
                "vendor_id": vid,
                "product_id": pid,
                "vendor_id_raw": vid,
                "product_id_raw": pid,
                "manufacturer": node.get("USB Vendor Name"),
                "serial_num": node.get("USB Serial Number"),
                "location_id": node.get("locationID"),
                "device_speed": node.get("Device Speed"),
            })
        walk_ioreg(node.get("IORegistryEntryChildren"), out)


def parse_ioreg_plist(payload: str) -> tuple[list[dict], str | None]:
    try:
        document = plistlib.loads(payload.encode())
    except (plistlib.InvalidFileException, ValueError, ExpatError) as error:
        return [], f"ioreg plist output is not a readable plist: {error}"
    devices: list[dict] = []
    walk_ioreg(document if isinstance(document, list) else [document], devices)
    return devices, None


#: One `ioreg -l` property line, e.g. `    "idVendor" = 1027`.
_IOREG_LINE = re.compile(r'"([^"]+)"\s*=\s*(?:"([^"]*)"|(-?\d+))')

#: Start of one `ioreg -l` node, e.g. `+-o ULX3S FPGA 85K v3.0.8@01100000`.
_IOREG_NODE = re.compile(r"^\s*[+|\s-]*\+-o\s+(.*?)(?:@[0-9a-fA-F]+)?\s*<")


def parse_ioreg_text(payload: str) -> tuple[list[dict], str | None]:
    """Parse plain ``ioreg -p IOUSB -l`` output, one node at a time."""
    devices: list[dict] = []
    name: str | None = None
    properties: dict[str, object] = {}

    def flush() -> None:
        vid, pid = properties.get("idVendor"), properties.get("idProduct")
        if isinstance(vid, int) and isinstance(pid, int):
            devices.append({
                "name": properties.get("USB Product Name") or name,
                "vendor_id": vid,
                "product_id": pid,
                "vendor_id_raw": vid,
                "product_id_raw": pid,
                "manufacturer": properties.get("USB Vendor Name"),
                "serial_num": properties.get("USB Serial Number"),
                "location_id": properties.get("locationID"),
                "device_speed": properties.get("Device Speed"),
            })

    for line in payload.splitlines():
        node = _IOREG_NODE.match(line)
        if node:
            flush()
            name, properties = node.group(1).strip(), {}
            continue
        field = _IOREG_LINE.search(line)
        if field:
            key, text, number = field.groups()
            properties[key] = int(number) if number is not None else text
    flush()
    return devices, None


USB_PARSERS = {
    "system_profiler": parse_usb,
    "ioreg-plist": parse_ioreg_plist,
    "ioreg-text": parse_ioreg_text,
}


def redact_probe(probe: dict, include_detail: bool) -> dict:
    """Replace a raw USB capture with a digest of it.

    The raw output of a USB enumeration is a list of everything plugged into
    the machine, serial numbers included, so it is not embedded by default.
    The length and SHA-256 keep it checkable against a locally re-run command
    without the contents travelling with the artifact.
    """
    if include_detail:
        return probe
    raw = probe["stdout"]
    return {
        **probe,
        "stdout": "",
        "stdout_bytes": len(raw.encode()),
        "stdout_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "stdout_withheld": (
            "raw USB enumeration lists every attached device; re-run the command "
            "locally, or pass --include-usb-detail, to see it"
        ),
    }


def redact(devices: list[dict], matches: list[dict], include_detail: bool) -> list[dict]:
    """Keep what identifies the board; drop what identifies its owner.

    An artifact can end up attached to a pull request, so devices that are not
    the board are reduced to a vendor/product identity, and the board's own
    serial number is withheld unless it is explicitly asked for.
    """
    matched = {id(device) for device in matches}
    kept = []
    for device in devices:
        if id(device) in matched:
            entry = dict(device)
            if not include_detail:
                entry["serial_num"] = REDACTED if device.get("serial_num") else None
            entry["location_id"] = REDACTED if device.get("location_id") else None
            kept.append(entry)
        else:
            kept.append({
                "name": REDACTED,
                "vendor_id": device["vendor_id"],
                "product_id": device["product_id"],
                "vendor_id_raw": REDACTED,
                "product_id_raw": REDACTED,
                "manufacturer": REDACTED,
                "serial_num": None,
                "location_id": None,
                "device_speed": None,
            })
    return kept


def capture_usb(system: str, include_detail: bool = False) -> dict:
    """Enumerate USB on Darwin, and refuse to guess anywhere else."""
    if system != "Darwin":
        return {
            "source": "unsupported",
            "supported": False,
            "probes": [],
            "devices": [],
            "matches": [],
            "detail": (
                f"USB enumeration in this tool is macOS-only and this host is "
                f"{system}. fpga_harness/board_detect.py reads /sys/bus/usb/devices, "
                f"which is Linux sysfs; neither probe is claimed to work here."
            ),
        }

    probes = []
    devices: list[dict] = []
    source = None
    for label, command in USB_COMMANDS:
        probe = run(command)
        if probe["returncode"] == 0:
            parsed, parse_error = USB_PARSERS[label](probe["stdout"])
        else:
            parsed, parse_error = [], (
                probe["error"] or f"{command[0]} exited {probe['returncode']}")
        probes.append({"source": label, "probe": redact_probe(probe, include_detail),
                       "parse_error": parse_error, "device_count": len(parsed)})
        if parsed and source is None:
            devices, source = parsed, label

    matches = [
        device for device in devices
        if device["vendor_id"] == ULX3S_USB_VID and device["product_id"] == ULX3S_USB_PID
    ]
    empty = [entry["source"] for entry in probes if entry["device_count"] == 0]
    return {
        "source": source or "none",
        "supported": True,
        "probes": probes,
        "device_count": len(devices),
        "devices": redact(devices, matches, include_detail),
        "matches": redact(matches, matches, include_detail),
        "detail_redacted": not include_detail,
        "expected_identity": f"{ULX3S_USB_VID:#06x}:{ULX3S_USB_PID:#06x}",
        "empty_probes": empty,
        "detail": (
            f"{len(matches)} device(s) at the ULX3S USB identity out of "
            f"{len(devices)} enumerated, via {source or 'no probe that saw anything'}"
            + (f"; enumerated nothing: {', '.join(empty)}" if empty else "")
            + ". A USB descriptor is not fabric behaviour."
        ),
    }


def capture_tools() -> dict:
    """Probe every version flag, and prefer a clean exit over a salvaged one.

    openFPGALoader 1.1.1 rejects ``--version`` and some builds print a version
    to stderr and still exit non-zero, so a non-zero exit is not treated as
    absence of a version. It is recorded as one, and flagged as salvaged.
    """
    tools: dict[str, dict] = {}
    for name in PROBED_TOOLS:
        path = shutil.which(name)
        entry: dict = {"path": path, "version": None, "version_command": None,
                       "version_exit_nonzero": False, "probes": []}
        if path is None:
            tools[name] = entry
            continue
        salvage = None
        for flag in VERSION_FLAGS:
            probe = run((name, flag), timeout=15)
            entry["probes"].append(probe)
            text = f"{probe['stdout']}{probe['stderr']}".strip()
            if not text:
                continue
            first = text.splitlines()[0].strip()
            if probe["returncode"] == 0:
                entry["version"] = first
                entry["version_command"] = probe["command"]
                break
            if salvage is None and VERSION_RE.search(first):
                salvage = (first, probe["command"])
        if entry["version"] is None and salvage is not None:
            entry["version"], entry["version_command"] = salvage
            entry["version_exit_nonzero"] = True
        tools[name] = entry
    return tools


def capture_jtag() -> dict:
    probes = [run(command, timeout=30) for command in JTAG_COMMANDS]
    combined = "".join(f"{probe['stdout']}{probe['stderr']}" for probe in probes)
    idcodes = [int(value, 16) for value in IDCODE_RE.findall(combined)]
    recognised = [
        {"idcode": f"{code:#010x}", "device": ECP5_IDCODES[code]}
        for code in idcodes if code in ECP5_IDCODES
    ]
    unrecognised = [f"{code:#010x}" for code in idcodes if code not in ECP5_IDCODES]
    answered = [probe["command"] for probe in probes if probe["returncode"] == 0]
    return {
        "probes": probes,
        "answered": answered,
        "idcodes": [f"{code:#010x}" for code in idcodes],
        "recognised": recognised,
        "unrecognised": unrecognised,
        "scan_text": clip(combined)[0],
        "detail": (
            "an IDCODE identifies silicon on the JTAG chain. It says nothing "
            "about which design is loaded or whether it works."
        ),
    }


def build_fixture(tools: dict, usb: dict, jtag: dict) -> dict:
    """Emit exactly the shape fpga_harness/board_detect.py --fixture consumes."""
    return {
        "_comment": (
            "Captured on macOS by tools/ulx3s_mac_preflight.py and replayed through "
            "fpga_harness/board_detect.py unmodified. The USB layer comes from "
            "system_profiler because that script's sysfs probe is Linux-only. "
            "Replay does not raise the datapath level; nothing here is data-path evidence."
        ),
        "tools": {name: entry["path"] for name, entry in tools.items() if entry["path"]},
        "versions": {
            name: entry["version"] for name, entry in tools.items() if entry["version"]
        },
        "usb_devices": [
            [device["vendor_id"], device["product_id"], device["name"] or "unnamed"]
            for device in usb.get("devices", [])
        ],
        "jtag_scan": jtag["scan_text"],
    }


def next_stage(root: pathlib.Path) -> dict:
    prerequisites = []
    for key, description, finder in NEXT_STAGE_PREREQUISITES:
        try:
            found = finder(root)
        except (OSError, UnicodeDecodeError) as error:
            found = []
            description = f"{description} (probe failed: {error})"
        prerequisites.append({
            "key": key,
            "requires": description,
            "present": bool(found),
            "found": found,
        })
    missing = [item["key"] for item in prerequisites if not item["present"]]
    return {
        "ready": not missing,
        "missing": missing,
        "prerequisites": prerequisites,
        "commands": [
            {"stage": stage, "purpose": purpose, "command": command}
            for stage, purpose, command in NEXT_STAGE_COMMANDS
        ],
        "policy": (
            "This block is a command shape, not a runnable stage. It stays closed "
            "until every prerequisite above exists in the tree, and satisfying them "
            "still only enables stage 4; data-path validation additionally requires "
            "a recorded byte log reproduced on a second board "
            "(fpga_harness/BUILD_PLAN.md stage 5)."
        ),
    }


def checklist(confirmations: dict[str, str]) -> list[dict]:
    return [
        {
            "key": key,
            "question": question,
            "where_to_look": where,
            "status": "confirmed" if key in confirmations else "unconfirmed",
            "value": confirmations.get(key),
        }
        for key, question, where in CHECKLIST
    ]


def repo_head() -> str | None:
    try:
        finished = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return finished.stdout.strip() or None


def render(artifact: dict) -> str:
    usb, jtag = artifact["usb"], artifact["jtag"]
    lines = ["ULX3S macOS preflight (visibility only, not data-path validation)"]
    lines.append(f"  host: {artifact['host']['platform']} {artifact['host']['release']} "
                 f"({artifact['host']['machine']})")
    if not usb["supported"]:
        lines.append(f"  usb:  UNSUPPORTED on this platform - {usb['detail']}")
    else:
        mark = "ok" if usb["matches"] else "--"
        lines.append(f"  [{mark}] usb: {usb['detail']}")
        for device in usb["matches"]:
            lines.append(f"        {device['vendor_id']:#06x}:{device['product_id']:#06x} "
                         f"{device['name']} serial={device['serial_num']}")
        for entry in usb["probes"]:
            lines.append(f"        probe {entry['source']}: "
                         f"{entry['device_count']} device(s)"
                         + (f", {entry['parse_error']}" if entry["parse_error"] else ""))
    found = [f"{name}={entry['version'] or entry['path']}"
             for name, entry in artifact["tools"].items() if entry["path"]]
    lines.append(f"  [{'ok' if found else '--'}] tools: {', '.join(found) or 'none on PATH'}")
    mark = "ok" if jtag["recognised"] else "--"
    lines.append(f"  [{mark}] jtag: "
                 + (", ".join(f"{item['idcode']} {item['device']}" for item in jtag["recognised"])
                    or "no recognised ECP5 IDCODE"))
    unconfirmed = [item["key"] for item in artifact["checklist"] if item["status"] != "confirmed"]
    lines.append(f"  checklist unconfirmed: {', '.join(unconfirmed) or 'none'}")
    lines.append(f"  next stage ready: {'yes' if artifact['next_stage']['ready'] else 'NO'}"
                 f" (missing: {', '.join(artifact['next_stage']['missing']) or 'nothing'})")
    lines.append("  data-path behaviour validated: NO")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=pathlib.Path,
                        help="write the preflight artifact JSON here")
    parser.add_argument("--fixture-out", type=pathlib.Path,
                        help="write a fpga_harness/board_detect.py --fixture file here")
    parser.add_argument("--confirm", action="append", default=[], metavar="KEY=VALUE",
                        help="record a human-confirmed checklist answer; repeatable")
    parser.add_argument("--next-stage", action="store_true",
                        help="print the bitstream/byte-log command shape and exit "
                             "non-zero while its prerequisites are missing")
    parser.add_argument("--include-usb-detail", action="store_true",
                        help="record the board serial, the names of unrelated attached "
                             "devices, and the raw USB enumeration; all withheld by "
                             "default because the artifact is meant to be attached to a PR")
    parser.add_argument("--json", action="store_true", help="print the artifact as JSON")
    args = parser.parse_args(argv)

    confirmations = {}
    for item in args.confirm:
        key, separator, value = item.partition("=")
        if not separator:
            parser.error(f"--confirm expects KEY=VALUE, got {item!r}")
        if key not in {entry[0] for entry in CHECKLIST}:
            parser.error(f"unknown checklist key {key!r}; "
                         f"expected one of {', '.join(entry[0] for entry in CHECKLIST)}")
        confirmations[key] = value

    system = platform.system()
    usb = capture_usb(system, include_detail=args.include_usb_detail)
    tools = capture_tools()
    jtag = capture_jtag()
    stage = next_stage(ROOT)

    artifact = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "generated_from_repo_head": repo_head(),
        "host": {
            "platform": system,
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "connection": {
            "port": "US1",
            "cable": "USB-C (Mac) to Micro-B (US1), data-capable",
            "note": "a charge-only cable powers the board but enumerates nothing",
        },
        "prior_hardware_evidence": {
            "record": "results/ulx3s-hardware-preflight-macos-20260725/README.md",
            "note": (
                "One macOS capture against a physical ULX3S-85F has been reviewed. "
                "It is what confirmed the USB identity and the ECP5 IDCODE against "
                "real hardware, and what showed the system_profiler and bare "
                "--detect failures this tool now works around. It is a separate "
                "record; nothing in this artifact inherits its results."
            ),
        },
        "usb": usb,
        "tools": tools,
        "jtag": jtag,
        "checklist": checklist(confirmations),
        "board_detect_fixture": build_fixture(tools, usb, jtag),
        "next_stage": stage,
        "claims": {
            "establishes": [
                "which loader/build tools exist on this Mac and at which versions",
                "whether macOS enumerates a device at the ULX3S USB identity",
                "whether an ECP5 TAP answers openFPGALoader --detect with an IDCODE",
            ],
            "does_not_establish": [
                "that any bitstream is loaded or correct",
                "that host bytes crossed the LSC-1 8-bit ready/valid pins",
                "anything about the ASIC RTL, its protocol behaviour, or timing closure",
                "any leanVM-b equivalence result; the data-path gate remains the "
                "official Rust comparison in tools/host_upstream_comparison.py",
            ],
            "known_limits": [
                "fpga_harness/board_detect.py enumerates USB from /sys/bus/usb/devices, "
                "which does not exist on macOS; its usb level is a false negative on "
                "Darwin and is not used here",
                "fpga_harness/board_detect.py scans JTAG with a bare `openFPGALoader "
                "--detect`, which exits 1 on a ULX3S because the default cable is "
                "FT2232; its jtag level is a false negative there too. That file is "
                "owned by the ULX3S harness lane and is not modified here",
                "system_profiler SPUSBDataType returned an empty tree on macOS 26.5.2 "
                "with a board attached, so it is probed first but never trusted alone; "
                "ioreg is the fallback and the source field says which one answered",
                "checklist entries are human observations; unconfirmed means unknown, "
                "not absent",
                "the board serial, unrelated attached devices and the raw USB "
                "enumeration are withheld by default so an artifact can be attached "
                "to a pull request; a SHA-256 of each raw capture is kept instead",
            ],
        },
    }

    if args.fixture_out:
        args.fixture_out.parent.mkdir(parents=True, exist_ok=True)
        args.fixture_out.write_text(
            json.dumps(artifact["board_detect_fixture"], indent=2, sort_keys=True) + "\n")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")

    if args.next_stage:
        print(json.dumps(stage, indent=2, sort_keys=True) if args.json else render_stage(stage))
        if not stage["ready"]:
            print(f"next stage refused: missing {', '.join(stage['missing'])}", file=sys.stderr)
            return 1
        return 0

    print(json.dumps(artifact, indent=2, sort_keys=True) if args.json else render(artifact))
    return 0


def render_stage(stage: dict) -> str:
    lines = ["Next-stage command shape (bitstream and byte log). Not run by this tool."]
    for item in stage["prerequisites"]:
        mark = "ok" if item["present"] else "--"
        lines.append(f"  [{mark}] {item['key']}: {item['requires']}")
        for path in item["found"]:
            lines.append(f"        {path}")
    lines.append("")
    for entry in stage["commands"]:
        lines.append(f"  {entry['stage']}: {entry['purpose']}")
        lines.append(f"      {entry['command']}")
    lines.append("")
    lines.append(f"  ready: {'yes' if stage['ready'] else 'NO'}")
    lines.append(f"  {stage['policy']}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())

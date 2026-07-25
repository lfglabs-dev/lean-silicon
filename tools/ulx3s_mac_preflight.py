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
ULX3S harness lane.  Its USB probe, ``_enumerate_usb``, reads
``/sys/bus/usb/devices``.  That path is Linux sysfs and does not exist on
macOS, so on Darwin the probe returns no devices and the ladder reports the
``usb`` level as absent *even with a board plugged in*.  That is a false
negative, not a board fault.

Rather than change another lane's file, this tool captures the USB layer with
``system_profiler SPUSBDataType`` and emits a fixture in the exact shape
``board_detect.py`` already documents for ``--fixture``.  The ladder is then
replayed unmodified, on this Mac or on any reviewer's machine:

    python3 tools/ulx3s_mac_preflight.py --out preflight.json \
        --fixture-out board.fixture.json
    python3 fpga_harness/board_detect.py --fixture board.fixture.json --json

Every capture keeps its raw output, so a parse this tool gets wrong is still
reviewable from the artifact.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import platform
import shutil
import subprocess
import sys
import types

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

USB_COMMAND = ("system_profiler", "SPUSBDataType", "-json")

#: openFPGALoader spells its version flag differently across releases, so try
#: each and record which one answered rather than assuming.
VERSION_FLAGS = ("--Version", "--version", "-V")

PROBED_TOOLS = (
    "openFPGALoader",
    "fujprog",
    "dfu-util",
    "yosys",
    "nextpnr-ecp5",
    "ecppack",
)

#: JTAG probes in order; the first that returns output wins, all are recorded.
JTAG_COMMANDS = (
    ("openFPGALoader", "--detect"),
    ("openFPGALoader", "-c", "ft232", "--detect"),
)

#: Physical facts no software probe on the Mac can establish.  Each is
#: `unconfirmed` until a human reads the board and passes --confirm.
CHECKLIST = (
    ("board_revision",
     "Which ULX3S board revision is this?",
     "Silkscreen on the PCB, near the ULX3S logo (for example 'ULX3S v3.0.8')."),
    ("fpga_density",
     "Which ECP5 density is fitted?",
     "The marking on the large Lattice package, e.g. LFE5U-85F-6BG381C. "
     "Cross-check against the JTAG IDCODE captured in this artifact."),
    ("sdram_part",
     "What is the SDRAM part number and size?",
     "The marking on the SDRAM chip, e.g. AS4C32M16SB-7TCN (32Mx16 = 64 MiB). "
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
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        return [], f"system_profiler output is not JSON: {error}"
    devices: list[dict] = []
    walk_usb(document.get("SPUSBDataType"), devices)
    return devices, None


def capture_usb(system: str) -> dict:
    """Enumerate USB on Darwin, and refuse to guess anywhere else."""
    if system != "Darwin":
        return {
            "source": "unsupported",
            "supported": False,
            "devices": [],
            "matches": [],
            "detail": (
                f"USB enumeration in this tool is macOS-only and this host is "
                f"{system}. fpga_harness/board_detect.py reads /sys/bus/usb/devices, "
                f"which is Linux sysfs; neither probe is claimed to work here."
            ),
        }
    probe = run(USB_COMMAND)
    if probe["returncode"] == 0:
        devices, parse_error = parse_usb(probe["stdout"])
    else:
        devices = []
        parse_error = probe["error"] or f"{USB_COMMAND[0]} exited {probe['returncode']}"
    matches = [
        device for device in devices
        if device["vendor_id"] == ULX3S_USB_VID and device["product_id"] == ULX3S_USB_PID
    ]
    return {
        "source": " ".join(USB_COMMAND),
        "supported": True,
        "probe": probe,
        "parse_error": parse_error,
        "device_count": len(devices),
        "devices": devices,
        "matches": matches,
        "expected_identity": f"{ULX3S_USB_VID:#06x}:{ULX3S_USB_PID:#06x}",
        "detail": (
            f"{len(matches)} device(s) at the ULX3S USB identity out of "
            f"{len(devices)} enumerated. A USB descriptor is not fabric behaviour."
        ),
    }


def capture_tools() -> dict:
    tools: dict[str, dict] = {}
    for name in PROBED_TOOLS:
        path = shutil.which(name)
        entry: dict = {"path": path, "version": None, "version_command": None, "probes": []}
        if path is not None:
            for flag in VERSION_FLAGS:
                probe = run((name, flag), timeout=15)
                entry["probes"].append(probe)
                text = f"{probe['stdout']}{probe['stderr']}".strip()
                if probe["returncode"] == 0 and text:
                    entry["version"] = text.splitlines()[0].strip()
                    entry["version_command"] = probe["command"]
                    break
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
    return {
        "probes": probes,
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
    usb = capture_usb(system)
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
                "the USB VID:PID and the ECP5 IDCODE table are vendor-documented values "
                "imported from fpga_harness/board_detect.py, not confirmed against "
                "hardware in this repository (fpga_harness/INVENTORY.md section 5)",
                "checklist entries are human observations; unconfirmed means unknown, "
                "not absent",
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

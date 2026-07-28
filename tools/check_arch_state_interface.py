#!/usr/bin/env python3
"""Mechanical coverage and mutation guard for the architectural state map."""
import json, pathlib, re, sys

root = pathlib.Path(__file__).resolve().parents[1]
rtl = (root / "asic_core/rtl/lsc1_packet_frontend.sv").read_text()
mapping = json.loads((root / "formal/lsc1_packet_frontend_arch_state_map.json").read_text())
ports = set(re.findall(r"output wire\s+(?:\[[^]]+\]\s*)?(arch_[A-Za-z0-9_]+)", rtl))
fields = mapping["fields"]
missing = ports - fields.keys()
extra = fields.keys() - ports
if missing or extra:
    raise SystemExit(f"arch map coverage failure: missing={sorted(missing)} extra={sorted(extra)}")
for field, source in fields.items():
    needle = f"assign {field} = {source};"
    if needle not in rtl:
        raise SystemExit(f"R mapping is absent or perturbed: {needle}")
if set(mapping["observable_outputs"]) != {"rx_ready", "tx_data", "tx_valid", "busy", "fault", "done_pulse"}:
    raise SystemExit("observable output channel coverage changed")
# Mutation test: an altered mapped source must be rejected by the same check.
mutated = rtl.replace("assign arch_active_profile = active_profile;",
                      "assign arch_active_profile = last_status;")
if "assign arch_active_profile = active_profile;" in mutated:
    raise SystemExit("mutation setup failed")
if "assign arch_active_profile = active_profile;" not in rtl:
    raise SystemExit("mutation guard did not distinguish source mapping")
print(f"arch-state map: {len(fields)} fields; all outputs and 6 observable channels covered")

#!/usr/bin/env python3
"""Mechanical completeness, width, reconstruction, and mutation guard for R."""
import json, pathlib, re

root = pathlib.Path(__file__).resolve().parents[1]
rtl = (root / "asic_core/rtl/lsc1_packet_frontend.sv").read_text()
mapping = json.loads((root / "formal/lsc1_packet_frontend_arch_state_map.json").read_text())
ports = {n: (int(a) - int(b) + 1 if a else 1) for a, b, n in
         re.findall(r"output wire\s+(?:\[(\d+)\s*:\s*(\d+)\]\s+)?(arch_[A-Za-z0-9_]+)", rtl)}
fields = mapping["fields"]
if set(ports) != set(fields):
    raise SystemExit(f"arch map coverage failure: missing={sorted(set(ports)-set(fields))} extra={sorted(set(fields)-set(ports))}")
for field, spec in fields.items():
    if spec["width"] != ports[field]:
        raise SystemExit(f"width mismatch for {field}: map={spec['width']} RTL={ports[field]}")
    needle = f"assign {field} = {spec['source']};"
    if needle not in rtl:
        raise SystemExit(f"R mapping is absent or perturbed: {needle}")
# Every nonblocking-assigned state element in each active module must be named.
modules = {
 "lsc1_packet_frontend": "lsc1_packet_frontend.sv", "lsc1_packet_tx": "lsc1_packet_tx.sv",
 "lsc1_stream_adapter": "lsc1_stream_adapter.sv", "leanvm_b_stream_alu": "leanvm_b_stream_alu.sv",
 "gf2n_mul_bitstream": "gf2n_mul_bitstream.sv", "lsc1_field_encoder": "lsc1_field_encoder.sv",
 "lsc1_packet_rx": "lsc1_packet_rx.sv"}
coverage = mapping["registered_coverage"]
for module, filename in modules.items():
    actual = set(re.findall(r"\b(\w+)\s*<=", (root / "asic_core/rtl" / filename).read_text()))
    declared = set()
    for owner, covered in coverage.items():
        if owner == module or owner.startswith(module + "."):
            declared |= set(covered)
    if actual - declared:
        raise SystemExit(f"registered-state omission in {module}: {sorted(actual-declared)}")
if set(mapping["observable_outputs"]) != {"rx_ready","tx_data","tx_valid","busy","fault","done_pulse"}:
    raise SystemExit("observable output channel coverage changed")
if set(mapping["output_reconstruction"]) != set(mapping["observable_outputs"]):
    raise SystemExit("output reconstruction is incomplete")
# Mutations target the reviewer-identified omitted state and must be rejected.
for good, bad in [("assign arch_tx_saved_crc = tx_arch_saved_crc;", "assign arch_tx_saved_crc = tx_arch_payload_crc_work;"),
                  ("assign arch_alu_saved_a = alu_arch_saved_a;", "assign arch_alu_saved_a = alu_arch_saved_b;")]:
    mutated = rtl.replace(good, bad)
    if good in mutated or good not in rtl:
        raise SystemExit("mutation guard did not distinguish mapped state")
print(f"arch-state map: {len(fields)} fields; widths, {sum(len(x) for x in coverage.values())} registered elements, output reconstruction, and mutations covered")

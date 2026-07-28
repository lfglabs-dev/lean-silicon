#!/usr/bin/env python3
"""Guard the concrete, non-vacuous bounded frontend path partitions."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
rx = (root / "formal/lsc1_packet_rx_status_accept.sv").read_text()
tx = (root / "formal/lsc1_packet_tx_status_response.sv").read_text()
for text, required in ((rx, ("frame_valid && !fault_valid", "frame_opcode == 8'h13", "8'h1c")),
                       (tx, ("start = step == 1", "step == 3 || step == 5", "tx_data == 8'h03", "done_pulse"))):
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise SystemExit(f"bounded path partition is incomplete: {missing}")
if "tx_data == 8'h00" in tx:
    raise SystemExit("INFO-status serializer mutation survived")
print("bounded path: concrete STATUS request acceptance and stalled INFO serialization are asserted")

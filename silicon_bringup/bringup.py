"""Pin-level dry-run driver for the implemented ``tt_um_lfglabs_lsc1u`` top.

It is intentionally a model transport.  It must never be used as evidence of
board or fabricated-silicon execution.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

RX_VALID, RX_READY, TX_VALID, TX_READY = 1, 2, 4, 8
BUSY, FAULT, DONE, OUTPUT_ENABLES = 16, 32, 128, 0xB6
OPCODES = {"XOR": 1, "MUL": 2, "SET": 3}
ROOT = Path(__file__).resolve().parent


def gf128_mul(a: bytes, b: bytes) -> bytes:
    x, y, out = int.from_bytes(a, "little"), int.from_bytes(b, "little"), 0
    for _ in range(128):
        if y & 1:
            out ^= x
        y >>= 1
        x = ((x << 1) & ((1 << 128) - 1)) ^ (0x87 if x >> 127 else 0)
    return out.to_bytes(16, "little")


def payload(case: dict) -> bytes:
    a = bytes.fromhex(case["a"])
    if case["opcode"] == "SET":
        return a
    b = bytes.fromhex(case["b"])
    return b"".join(bytes((x, y)) for x, y in zip(a, b)) if case["opcode"] == "XOR" else a + b


def oracle(case: dict) -> bytes:
    """Compute the result independently of the pin-model state machine."""
    a = bytes.fromhex(case["a"])
    if len(a) != 16:
        raise ValueError("operand a must contain 16 bytes")
    if case["opcode"] == "SET":
        return a
    b = bytes.fromhex(case["b"])
    if len(b) != 16:
        raise ValueError("operand b must contain 16 bytes")
    if case["opcode"] == "XOR":
        return bytes(x ^ y for x, y in zip(a, b))
    if case["opcode"] == "MUL":
        return gf128_mul(a, b)
    raise ValueError(f"unsupported opcode {case['opcode']!r}")


@dataclass(frozen=True)
class Pins:
    uo_out: int
    uio_out: int
    uio_oe: int


class DryRunBackend:
    """Deterministic pin model; it models protocol states, not silicon timing."""
    def __init__(self):
        self.reset_state()
        self.ui_in = self.uio_in = 0
        self.ena = self.rst_n = True

    def reset_state(self):
        self.command = None; self.incoming = bytearray(); self.outgoing = bytearray()
        self.input_count = self.responses_acked = self.response_total = 0
        self.mul_bits_remaining = 0; self.pending_mul_result = None; self.mul_tx_bubble = False
        self.fault = False; self.done = False

    def drive(self, *, ui_in: int, uio_in: int, ena: bool, rst_n: bool):
        self.ui_in, self.uio_in, self.ena, self.rst_n = ui_in, uio_in, ena, rst_n

    def pins(self) -> Pins:
        if not self.ena:
            return Pins(0, 0, 0)
        status = (RX_READY if not self.outgoing and not self.mul_bits_remaining and self.pending_mul_result is None else 0) | (TX_VALID if self.outgoing and not self.mul_tx_bubble else 0)
        status |= BUSY if self.command is not None or self.outgoing else 0
        status |= FAULT if self.fault else 0
        status |= DONE if self.done and self.rst_n else 0
        return Pins(self.outgoing[0] if self.outgoing else 0, status, OUTPUT_ENABLES)

    def cycle(self) -> Pins:
        before = self.pins()
        if not self.ena or not self.rst_n:
            self.reset_state()
            return before
        self.done = False
        tx_fire = bool(before.uio_out & TX_VALID and self.uio_in & TX_READY)
        rx_fire = bool(before.uio_out & RX_READY and self.uio_in & RX_VALID)
        if self.mul_tx_bubble:
            self.mul_tx_bubble = False
        if self.mul_bits_remaining:
            self.mul_bits_remaining -= 1
        elif self.pending_mul_result is not None:
            self.outgoing = bytearray(self.pending_mul_result)
            self.pending_mul_result = None
        if tx_fire:
            self.outgoing.pop(0)
            self.responses_acked += 1
            if self.responses_acked == self.response_total:
                self.done, self.command, self.fault = True, None, False
            elif self.command == OPCODES["MUL"]:
                self.mul_tx_bubble = True
        if rx_fire:
            if self.command is None:
                self.incoming.clear()
                self.input_count = self.responses_acked = self.response_total = 0
                self.command = self.ui_in
                if self.command not in OPCODES.values():
                    self.outgoing, self.fault, self.response_total = bytearray((0xE0,)), True, 1
            else:
                self.incoming.append(self.ui_in)
                self.input_count += 1
                size = 16 if self.command == OPCODES["SET"] else 32
                if self.command == OPCODES["SET"]:
                    self.outgoing, self.response_total = bytearray((self.ui_in,)), 16
                elif self.command == OPCODES["XOR"] and self.input_count % 2 == 0:
                    self.outgoing, self.response_total = bytearray((self.incoming[-2] ^ self.incoming[-1],)), 16
                elif self.command == OPCODES["MUL"] and self.input_count > 16:
                    self.mul_bits_remaining = 7
                    if len(self.incoming) == size:
                        data = bytes(self.incoming)
                        self.pending_mul_result, self.incoming = gf128_mul(data[:16], data[16:]), bytearray()
                        self.response_total = 16
        return before


class Driver:
    def __init__(self, backend: DryRunBackend): self.backend = backend
    def _cycle(self, ui=0, uio=0, ena=True, rst_n=True) -> Pins:
        self.backend.drive(ui_in=ui, uio_in=uio, ena=ena, rst_n=rst_n)
        return self.backend.cycle()
    def idle(self) -> Pins:
        self._cycle(); return self._cycle()
    def reset(self): self._cycle(rst_n=False); return self.idle()
    def deselect_abort(self): self._cycle(ena=False); self._cycle(ena=False); return self.idle()
    def send(self, byte: int):
        while not self.backend.pins().uio_out & RX_READY:
            self._cycle()
        self._cycle(byte, RX_VALID); self._cycle()
    def receive_all(self) -> tuple[bytes, bool]:
        answer = bytearray()
        while True:
            pins = self.backend.pins()
            if pins.uio_out & TX_VALID:
                answer.append(pins.uo_out)
                self._cycle(uio=TX_READY)
            elif self.backend.command is not None and not pins.uio_out & RX_READY:
                self._cycle()
            else:
                break
        observed_done = bool(self.backend.pins().uio_out & DONE)
        self._cycle()
        return bytes(answer), observed_done
    def run(self, case: dict) -> dict:
        received = bytearray()
        done = False
        self.send(OPCODES[case["opcode"]])
        for value in payload(case):
            self.send(value)
            if self.backend.pins().uio_out & TX_VALID:
                # The RTL applies backpressure after every SET/XOR result byte.
                part, retired = self.receive_all()
                received.extend(part); done |= retired
        while (self.backend.command is not None and
               not self.backend.pins().uio_out & (RX_READY | TX_VALID)):
            self._cycle()
        part, retired = self.receive_all()
        received.extend(part); done |= retired
        return {"answer": bytes(received), "done": done}


def run_case(case: dict) -> dict:
    driver = Driver(DryRunBackend()); driver.reset()
    received = bytearray()
    driver.send(OPCODES[case["opcode"]])
    done = False
    for value in payload(case):
        driver.send(value)
        if driver.backend.pins().uio_out & TX_VALID:
            part, retired = driver.receive_all(); received.extend(part); done |= retired
    while (driver.backend.command is not None and
           not driver.backend.pins().uio_out & (RX_READY | TX_VALID)):
        driver._cycle()
    part, retired = driver.receive_all(); received.extend(part); done |= retired
    expected = oracle(case)
    if bytes.fromhex(case["expected"]) != expected:
        raise ValueError(f"vector {case['id']!r} disagrees with independent oracle")
    return {"id": case["id"], "opcode": case["opcode"], "received": received.hex(), "expected": expected.hex(), "oracle_match": received == expected, "retire_done_pulse": done, "idle_after_retire": bool(driver.backend.pins().uio_out & RX_READY) and not bool(driver.backend.pins().uio_out & BUSY)}


def receipt() -> dict:
    vectors = json.loads((ROOT / "vectors.json").read_text())["cases"]
    observations = [run_case(case) for case in vectors]
    passed = all(x["oracle_match"] and x["retire_done_pulse"] and x["idle_after_retire"] for x in observations)
    failures = [x["id"] for x in observations if not (x["oracle_match"] and x["retire_done_pulse"] and x["idle_after_retire"])]
    return {"schema": "lean-silicon.lsc1u-bringup-receipt.v1", "execution": {"kind": "dry-run", "real_silicon": False, "transport": "deterministic Python pin-model"}, "interface": {"top": "tt_um_lfglabs_lsc1u", "uio_oe": "0xb6", "abort": "synchronous rst_n=0 or ena=0; uio[6] is reserved and ignored", "reserved_input_bits": [6]}, "vectors": [x["id"] for x in vectors], "observations": observations, "oracle": {"algorithm": "independent GF(2^128), little-endian, low reduction 0x87", "matched": all(x["oracle_match"] for x in observations)}, "outcome": {"passed": passed, "failures": failures}}


def validate_receipt(document: dict) -> None:
    """Dependency-free enforcement of the safety-critical schema invariants."""
    required = {"schema", "execution", "interface", "vectors", "observations", "oracle", "outcome"}
    if set(document) != required or document["schema"] != "lean-silicon.lsc1u-bringup-receipt.v1":
        raise ValueError("not an LSC-1u bring-up receipt v1")
    execution, interface = document["execution"], document["interface"]
    if (not isinstance(execution, dict) or set(execution) != {"kind", "real_silicon", "transport"} or
            execution.get("kind") not in {"dry-run", "simulation", "hardware"} or
            not isinstance(execution.get("transport"), str) or not execution["transport"]):
        raise ValueError("invalid execution record")
    if type(execution.get("real_silicon")) is not bool or execution["real_silicon"] != (execution["kind"] == "hardware"):
        raise ValueError("execution kind and real_silicon disagree")
    if execution["kind"] == "hardware":
        raise ValueError("receipt v1 cannot verify independent hardware provenance")
    if execution["transport"] == "deterministic Python pin-model" and execution["kind"] != "dry-run":
        raise ValueError("deterministic pin-model transport is dry-run evidence only")
    if interface != {"top": "tt_um_lfglabs_lsc1u", "uio_oe": "0xb6", "abort": "synchronous rst_n=0 or ena=0; uio[6] is reserved and ignored", "reserved_input_bits": [6]}:
        raise ValueError("receipt does not identify the implemented Tiny Tapeout pin contract")
    vectors, observations = document["vectors"], document["observations"]
    if (not isinstance(vectors, list) or not vectors or
            any(not isinstance(item, str) or not item for item in vectors) or
            len(vectors) != len(set(vectors))):
        raise ValueError("invalid vector identifiers")
    if not isinstance(observations, list) or len(observations) != len(vectors):
        raise ValueError("observations do not cover the declared vectors")
    cases = {case["id"]: case for case in json.loads((ROOT / "vectors.json").read_text())["cases"]}
    if vectors != list(cases):
        raise ValueError("receipt does not cover the complete shipped vector corpus")
    required_observation = {"id", "opcode", "received", "expected", "oracle_match", "retire_done_pulse", "idle_after_retire"}
    for vector_id, observation in zip(vectors, observations):
        if (not isinstance(observation, dict) or set(observation) != required_observation or
                observation["id"] != vector_id or observation["opcode"] not in OPCODES or
                any(type(observation[key]) is not bool for key in ("oracle_match", "retire_done_pulse", "idle_after_retire"))):
            raise ValueError("invalid observation record")
        try:
            received = bytes.fromhex(observation["received"])
            expected = bytes.fromhex(observation["expected"])
        except (TypeError, ValueError) as error:
            raise ValueError("observation results must be hexadecimal") from error
        if len(received) != 16 or len(expected) != 16 or observation["oracle_match"] != (received == expected):
            raise ValueError("observation result or oracle verdict is inconsistent")
        case = cases.get(vector_id)
        if case is None or observation["opcode"] != case["opcode"] or expected != oracle(case):
            raise ValueError("observation is not bound to the shipped deterministic vector")
    matched = all(item["oracle_match"] for item in observations)
    oracle_record = document["oracle"]
    if oracle_record != {"algorithm": "independent GF(2^128), little-endian, low reduction 0x87", "matched": matched}:
        raise ValueError("oracle summary is inconsistent")
    passed = all(item["oracle_match"] and item["retire_done_pulse"] and item["idle_after_retire"] for item in observations)
    failures = [] if passed else [item["id"] for item in observations if not (item["oracle_match"] and item["retire_done_pulse"] and item["idle_after_retire"])]
    if document["outcome"] != {"passed": passed, "failures": failures}:
        raise ValueError("outcome summary is inconsistent")

#!/usr/bin/env python3
"""Analytical design-space model for the streamed GF(2^128) multiplier.

The model deliberately counts only quantities that are exact for the declared
architecture family:

* sequential bits are the RTL registers required by the schedule;
* AND2/XOR2 counts are the direct radix-r digit-step network before synthesis;
* ideal cycles assume no host stalls and the protocol in docs/PROTOCOL.md.

It is not a Sky130 post-layout area estimator.  OpenLane reports remain the
source of truth for tile selection.
"""

from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass
from pathlib import Path


WORD_BITS = 128
BUS_BITS = 8
WORD_BYTES = WORD_BITS // BUS_BITS
COMMON_ENGINE_STATE_BITS = 17  # state, byte index, shared scratch, sticky fault
MULTIPLIER_STATE_BITS = 2 * WORD_BITS  # shifted A and accumulator


@dataclass(frozen=True)
class Point:
    radix: int
    sequential_bits: int
    and2_digit_step: int
    xor2_digit_step: int
    simple_gate_total: int
    multiplication_cycles: int
    transaction_cycles: int
    area_latency_product: int
    min_area: bool = False
    min_latency: bool = False
    pareto: bool = False


def ceil_log2(n: int) -> int:
    return 0 if n <= 1 else math.ceil(math.log2(n))


def point(radix: int) -> Point:
    if radix not in (1, 2, 4, 8):
        raise ValueError("radix must divide an 8-bit input byte")

    # The shared eight-bit scratch register can carry the unconsumed digit
    # groups plus an in-band sentinel, so the parent needs no substep counter.
    sequential = MULTIPLIER_STATE_BITS + COMMON_ENGINE_STATE_BITS

    # For each of r multiplier bits: 128 ANDs select A*x^j.  Each output
    # accumulator bit XORs r selected terms with the old accumulator (r XOR2s).
    # Generating A*x, ..., A*x^r by repeated GHASH xtime costs three XOR2s per step.
    # The reduction taps are 0,1,2,7, but output bit 0 is the old carry
    # directly (a wire); only output bits 1,2,7 are XORs.
    and2 = WORD_BITS * radix
    xor2 = WORD_BITS * radix + 3 * radix
    gates = and2 + xor2

    mul_cycles = WORD_BITS // radix
    # One command beat + 16 A beats + multiplier digit beats + 16 result beats.
    transaction = 1 + WORD_BYTES + mul_cycles + WORD_BYTES
    return Point(
        radix=radix,
        sequential_bits=sequential,
        and2_digit_step=and2,
        xor2_digit_step=xor2,
        simple_gate_total=gates,
        multiplication_cycles=mul_cycles,
        transaction_cycles=transaction,
        area_latency_product=gates * transaction,
    )


def dominates(a: Point, b: Point) -> bool:
    metrics_a = (a.sequential_bits, a.simple_gate_total, a.transaction_cycles)
    metrics_b = (b.sequential_bits, b.simple_gate_total, b.transaction_cycles)
    return all(x <= y for x, y in zip(metrics_a, metrics_b)) and any(
        x < y for x, y in zip(metrics_a, metrics_b)
    )


def build() -> list[Point]:
    raw = [point(r) for r in (1, 2, 4, 8)]
    min_gates = min(p.simple_gate_total for p in raw)
    min_cycles = min(p.transaction_cycles for p in raw)
    result = []
    for p in raw:
        result.append(
            Point(
                **{
                    **asdict(p),
                    "min_area": p.simple_gate_total == min_gates,
                    "min_latency": p.transaction_cycles == min_cycles,
                    "pareto": not any(dominates(q, p) for q in raw if q != p),
                }
            )
        )
    return result


def write_outputs(points: list[Point], root: Path) -> None:
    csv_path = root / "design_space.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(points[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(p) for p in points)

    lines = [
        "# Streamed multiplier design-space results",
        "",
        "| Radix | State bits | AND2/step | XOR2/step | Simple gates | GF cycles | Transaction cycles | Area×latency | Pareto |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for p in points:
        lines.append(
            f"| {p.radix} | {p.sequential_bits} | {p.and2_digit_step} | "
            f"{p.xor2_digit_step} | {p.simple_gate_total} | "
            f"{p.multiplication_cycles} | {p.transaction_cycles} | "
            f"{p.area_latency_product} | {'yes' if p.pareto else 'no'} |"
        )
    lines.extend(
        [
            "",
            "* Radix 1 is exact minimum direct transition logic in this digit-serial family.",
            "* Radix 8 reaches the 49-cycle protocol lower bound when output starts only after both operands arrive.",
            "* All four points are Pareto-optimal under (state bits, direct digit-step gates, ideal cycles).",
            "* These are architecture counts, not post-layout Sky130 area estimates.",
        ]
    )
    (root / "design_space.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    points = build()
    out = Path(__file__).resolve().parent
    write_outputs(points, out)
    for p in points:
        tags = []
        if p.min_area:
            tags.append("minimum-logic")
        if p.min_latency:
            tags.append("minimum-latency")
        if p.pareto:
            tags.append("pareto")
        print(
            f"radix={p.radix}: state={p.sequential_bits} bits, "
            f"step={p.simple_gate_total} simple gates, "
            f"transaction={p.transaction_cycles} cycles "
            f"[{' '.join(tags)}]"
        )


if __name__ == "__main__":
    main()

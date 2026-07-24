#!/usr/bin/env python3
"""Exact XOR2 synthesis for leanVM-b GHASH ``xtime`` reduction taps.

Every linear Boolean form is represented by a bit mask over the relevant
inputs ``(a0, a1, a6, carry)``.  A two-input XOR gate creates the symmetric
difference of two available masks.  Breadth-first enumeration proves that no
network with fewer than three gates can expose all three required forms and
returns a minimum construction.

This is an exact result for the stated XOR2/free-wire/free-fanout model, not a
Sky130 mapped-cell result.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations


NAMES = ("a0", "a1", "a6", "carry")
INPUTS = tuple(1 << i for i in range(len(NAMES)))
TARGETS = frozenset((INPUTS[0] ^ INPUTS[3], INPUTS[1] ^ INPUTS[3], INPUTS[2] ^ INPUTS[3]))


@dataclass(frozen=True)
class Gate:
    left: int
    right: int
    output: int


def form(mask: int) -> str:
    terms = [name for i, name in enumerate(NAMES) if mask & (1 << i)]
    return " xor ".join(terms) if terms else "0"


def minimum_network() -> tuple[Gate, ...]:
    start = frozenset(INPUTS)
    frontier: dict[frozenset[int], tuple[Gate, ...]] = {start: ()}

    # A three-gate construction is known, so this finite search may stop at 3.
    for depth in range(4):
        for available, network in frontier.items():
            if TARGETS.issubset(available):
                return network
        if depth == 3:
            break

        next_frontier: dict[frozenset[int], tuple[Gate, ...]] = {}
        for available, network in frontier.items():
            for left, right in combinations(sorted(available), 2):
                output = left ^ right
                if output == 0 or output in available:
                    continue
                new_available = frozenset((*available, output))
                next_frontier.setdefault(
                    new_available, network + (Gate(left, right, output),)
                )
        frontier = next_frontier

    raise AssertionError("no network found through three XOR2 gates")


def main() -> None:
    network = minimum_network()
    assert len(network) == 3
    print("Exact GHASH xtime reduction-tap XOR2 minimum: 3 gates")
    print("Construction:")
    for index, gate in enumerate(network):
        print(f"  g{index} = ({form(gate.left)}) xor ({form(gate.right)}) = {form(gate.output)}")
    print("Required outputs:")
    for target in sorted(TARGETS):
        print(f"  {form(target)}")


if __name__ == "__main__":
    main()

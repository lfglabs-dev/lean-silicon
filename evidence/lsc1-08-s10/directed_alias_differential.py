#!/usr/bin/env python3
"""AC-5: directed frontend differential for the extracted cell alias precheck.

Builds directed request frames that exercise the three-cell alias predicate for
every opcode that evaluates it -- DEREF_CELL, DEREF_PC, DEREF_FP, JUMP, XOR and
MUL -- and drives each frame through two independently compiled frontends: the
base tree (the inline predicate, triplicated) and the head tree (the extracted
lsc1_cell_alias_check instance).  The responses must be byte-identical, which
pins (reject, fault_status, fault_detail) together since all three are carried in
the response bytes.

The frames are directed rather than random because the repository's seeded
differential suites do reach the predicate but never make it true: several JUMP
frames use offsets=(10, 11, 10), so cells a and c share an address, but the two
aliased cells are always byte-identical, so every pair term evaluates false.
That makes those suites sensitive to the predicate's *negative* verdict only --
see alias_coverage.md.  This script supplies the positive-verdict coverage.

Usage:
    python3 evidence/lsc1-08-s10/directed_alias_differential.py BASE_TREE HEAD_TREE
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RTL = [
    "asic_core/rtl/lsc1_packet_rx.sv",
    "asic_core/rtl/lsc1_packet_tx.sv",
    "asic_core/rtl/lsc1_response_payload_mux.sv",
    "asic_core/rtl/lsc1_blake3_alias_check.sv",
    "asic_core/rtl/lsc1_request_validator.sv",
    "asic_core/rtl/lsc1_blake3_lifecycle.sv",
    "asic_core/rtl/gf2n_mul_bitstream.sv",
    "asic_core/rtl/gf128_mul_bitstream.sv",
    "asic_core/rtl/leanvm_b_stream_alu.sv",
    "asic_core/rtl/lsc1_stream_adapter.sv",
    "asic_core/rtl/lsc1_field_encoder.sv",
    "asic_core/rtl/lsc1_packet_frontend.sv",
    "test/packet_frontend/tb_lsc1_packet_vector.sv",
]
EXTRACTED = "asic_core/rtl/lsc1_cell_alias_check.sv"

ALIAS_INCONSISTENT = 0x96


def build(tree: Path, out: Path) -> Path:
    sources = [str(tree / path) for path in RTL]
    extracted = tree / EXTRACTED
    if extracted.is_file():
        sources.insert(5, str(extracted))
    subprocess.run(
        ["iverilog", "-g2012", "-s", "tb_lsc1_packet_vector", "-o", str(out)] + sources,
        cwd=tree, check=True, capture_output=True, text=True,
    )
    return out


def exchange(simulator: Path, scratch: Path, tag: str, encoded: bytes) -> bytes:
    request = scratch / f"{tag}.hex"
    request.write_text("\n".join(f"{byte:02x}" for byte in encoded) + "\n")
    run = subprocess.run(
        ["vvp", str(simulator), f"+REQUEST={request}", f"+LENGTH={len(encoded)}"],
        check=True, capture_output=True, text=True,
    )
    line = next(item for item in run.stdout.splitlines() if item.startswith("RESPONSE "))
    return bytes.fromhex(line.removeprefix("RESPONSE "))


def frames(protocol):
    """Yield (name, opcode_label, pair, mode, frame) for every directed case."""
    Cell, ABSENT = protocol.Cell, protocol.ABSENT
    Opcode, Profile = protocol.Opcode, protocol.Profile
    profile = Profile.INTERPRETER_COMPAT

    # (fp, base_index, base offsets, the value the aliasing pair shares)
    variants = [
        (0, 0, (16, 32, 48), 0x11),
        (64, 7, (1, 2, 3), 0),
        (4096, 4095, (100, 200, 300), 0xDEADBEEF),
        (1, 65535, (5, 6, 7), (1 << 127)),
        (0xFFFF, 1234, (9, 21, 33), 0x0123456789ABCDEF0123456789ABCDEF),
    ]
    scalar_ops = [("XOR", Opcode.XOR), ("MUL", Opcode.MUL_NATIVE), ("JUMP", None)]
    deref_ops = [("DEREF_CELL", Opcode.DEREF_CELL), ("DEREF_PC", Opcode.DEREF_PC),
                 ("DEREF_FP", Opcode.DEREF_FP)]
    modes = ["distinct", "agree", "presence_disagree", "value_disagree"]

    txn = 0
    for label, opcode in deref_ops + scalar_ops:
        is_deref = label.startswith("DEREF")
        for pair in ("ab", "ac", "bc"):
            for mode in modes:
                for index, (fp, base, offsets, shared) in enumerate(variants):
                    txn += 1
                    off = list(offsets)
                    # Collide the chosen pair's addresses.  For DEREF the middle
                    # address is base_index + off_b; for the scalar layout every
                    # address is fp + off_*.
                    if mode != "distinct":
                        if pair == "ab":
                            off[1] = (fp + off[0] - base) if is_deref else off[0]
                        elif pair == "ac":
                            off[2] = off[0]
                        else:
                            off[2] = (base + off[1] - fp) if is_deref else off[1]
                    if any(value < 0 or value > 0xFFFFFFFF for value in off):
                        txn -= 1
                        continue
                    limit = 0xFFFFFFFF - fp
                    over = off[0] > limit or off[2] > limit
                    over = over or (off[1] > (0xFFFFFFFF - base if is_deref else limit))
                    if over:
                        txn -= 1
                        continue

                    cells = [Cell(True, shared), Cell(True, shared), Cell(True, shared)]
                    if mode == "distinct":
                        cells = [Cell(True, shared), Cell(True, shared + 1),
                                 Cell(True, shared + 2)]
                    elif mode == "presence_disagree":
                        # An absent cell must carry value 0 or the malformedness
                        # test ahead of the alias check fires first.
                        target = {"ab": 1, "ac": 2, "bc": 2}[pair]
                        cells[target] = ABSENT
                        cells[{"ab": 0, "ac": 0, "bc": 1}[pair]] = Cell(True, 0)
                        cells[{"ab": 2, "ac": 1, "bc": 0}[pair]] = Cell(True, 0xA5)
                    elif mode == "value_disagree":
                        target = {"ab": 1, "ac": 2, "bc": 2}[pair]
                        cells[target] = Cell(True, shared ^ 0xFF)

                    name = f"{label}_{pair}_{mode}_v{index}"
                    if is_deref:
                        frame = protocol.build_deref(
                            opcode, txn_id=txn, pc=index, fp=fp, profile=profile,
                            alpha=off[0], beta=off[1], gamma=off[2],
                            pointer=cells[0], base=base, target=cells[1],
                            local=cells[2])
                    elif label == "JUMP":
                        frame = protocol.build_jump(
                            txn_id=txn, pc=index, fp=fp, profile=profile,
                            offsets=tuple(off), cells=tuple(cells), taken=False,
                            dest_pc=0, dest_fp=0, proposed_inverse=ABSENT)
                    else:
                        frame = protocol.build_binary_op(
                            opcode, txn_id=txn, pc=index, fp=fp, profile=profile,
                            offsets=tuple(off), cells=tuple(cells),
                            proposed_inverse=ABSENT)
                    yield name, label, pair, mode, frame


def main() -> int:
    base_tree, head_tree = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    sys.path.insert(0, str(head_tree))
    from sim import lsc1_transaction as protocol

    cases = list(frames(protocol))
    with tempfile.TemporaryDirectory() as raw:
        scratch = Path(raw)
        base_sim = build(base_tree, scratch / "base.vvp")
        head_sim = build(head_tree, scratch / "head.vvp")

        def run(item):
            index, (name, label, pair, mode, frame) = item
            encoded = frame.encode()
            return (name, label, pair, mode,
                    exchange(base_sim, scratch, f"b{index}", encoded),
                    exchange(head_sim, scratch, f"h{index}", encoded))

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(run, enumerate(cases)))

    mismatches = [(name, base.hex(), head.hex())
                  for name, _, _, _, base, head in results if base != head]
    positives = Counter()
    over_fired = []
    for name, label, pair, mode, base, _ in results:
        fired = protocol.decode_response(base).status is protocol.Status.ALIAS_INCONSISTENT
        if fired:
            positives[(label, pair)] += 1
            if mode in ("distinct", "agree"):
                over_fired.append(name)

    print(f"directed frames: {len(results)}")
    print(f"alias-inconsistent verdicts observed: {sum(positives.values())}")
    for key in sorted(positives):
        print(f"  {key[0]:<11} pair {key[1]}: {positives[key]}")

    if mismatches:
        print(f"\nFAIL: {len(mismatches)} base/head response mismatches", file=sys.stderr)
        for name, base, head in mismatches[:10]:
            print(f"  {name}\n    base={base}\n    head={head}", file=sys.stderr)
        return 1
    if len(results) < 300:
        print(f"\nFAIL: only {len(results)} directed frames, expected at least 300",
              file=sys.stderr)
        return 1
    expected = {(label, pair)
                for label in ("DEREF_CELL", "DEREF_PC", "DEREF_FP", "JUMP", "XOR", "MUL")
                for pair in ("ab", "ac", "bc")}
    missing = sorted(expected - set(positives))
    if missing:
        print(f"\nFAIL: no alias-inconsistent verdict for {missing}", file=sys.stderr)
        return 1
    if over_fired:
        print(f"\nFAIL: alias verdict fired on {len(over_fired)} non-aliasing or "
              f"consistent frames, e.g. {over_fired[:5]}", file=sys.stderr)
        return 1

    print(f"\nPASS: {len(results)} directed frames byte-identical between base and head; "
          f"every opcode/pair combination reached the alias-inconsistent verdict")
    return 0


if __name__ == "__main__":
    sys.exit(main())

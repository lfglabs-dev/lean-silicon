# AC-4 falsifier correction: the seeded differentials cannot witness a positive alias verdict

Base commit: `497b905bbd85b85eaa3d222ab9775fdb1b27b643`

## What the scoping document asked for

AC-4 of `LSC1-08-S10-SCOPE.md` names its falsifier as: tie the extracted module's
`alias_inconsistent` output low and observe `sim/test_packet_frontend_rtl_differential.py`
turn red. That falsifier does **not** fire. This document records the measurement,
the root cause, and the substitute obligation that does fire.

## Measurement

Each run is `python3 -m unittest sim.test_packet_frontend_rtl_differential` from the
repository root.

| Tree | Predicate forced to | Exit | Result |
| --- | --- | --- | --- |
| head | (unmodified) | 0 | 18 tests pass |
| head | `1'b0` (tie low) | 0 | **18 tests still pass — falsifier does not fire** |
| head | `1'b1` (tie high) | 1 | 30 failures |
| base (497b905b), three inline arms forced to `if (1'b0)` | n/a | 0 | 18 tests still pass |

The tie-high row proves the predicate **is** reached and its value **is**
observable: forcing it true changes 30 responses. The tie-low row proves that on
every frame the suite generates, the predicate's true value already equals false.
So the suite constrains the negative verdict and nothing else.

The base row is the important one: the same insensitivity is present at
`497b905b` with the *inline* predicate short-circuited. This is a **pre-existing
coverage gap in the seeded suite**, not something the S10 extraction introduced.
Nothing in this slice made the suite weaker.

## Root cause

The predicate is

```
(addr_x == addr_y) && (present_x != present_y || value_x != value_y)
```

for the three pairs. Making it true needs *both* conjuncts: two cells on one
address **and** those two cells disagreeing.

The seeded suite does satisfy the first conjunct. Several JUMP frames in
`sim/test_packet_frontend_rtl_differential.py` are built with
`offsets=(10, 11, 10)`, so `addr_a == addr_c`. But their cells are

```python
cells=(protocol.Cell(True, 1), protocol.Cell(True, protocol.field_encode(15)), protocol.Cell(True, 1))
```

— cells a and c are byte-identical in both presence and value. The second
conjunct is therefore false, and the pair term collapses. Every other frame in
the suite draws its three offsets from distinct small constants
(`(1,2,3)`, `(0,1,2)`, `(4,5,6)`, `(10,11,12)`, `(2,3,4)`), so not even the
address-equality conjunct holds.

The gap is precise: the suite exercises the address comparator and the
consistency comparator, but never the conjunction of "aliased" with
"disagreeing". No frame in it is a positive witness.

## Substitute obligation

`evidence/lsc1-08-s10/directed_alias_differential.py` (AC-5) supplies exactly the
missing coverage, and it is the load-bearing frontend-level falsifier for this
slice. It builds directed frames that collide a chosen pair's addresses and then
make that pair disagree, for every opcode that evaluates the predicate.

```
$ python3 evidence/lsc1-08-s10/directed_alias_differential.py /root/work/s10/base /root/work/s10/repo
directed frames: 333
alias-inconsistent verdicts observed: 162
  DEREF_CELL  pair ab: 8      JUMP  pair ab: 10      XOR  pair ab: 10
  DEREF_CELL  pair ac: 10     JUMP  pair ac: 10      XOR  pair ac: 10
  DEREF_CELL  pair bc: 6      JUMP  pair bc: 10      XOR  pair bc: 10
  DEREF_PC    pair ab: 8      MUL   pair ab: 10
  DEREF_PC    pair ac: 10     MUL   pair ac: 10
  DEREF_PC    pair bc: 6      MUL   pair bc: 10
  DEREF_FP    pair ab: 8
  DEREF_FP    pair ac: 10
  DEREF_FP    pair bc: 6
PASS: 333 directed frames byte-identical between base and head; every
opcode/pair combination reached the alias-inconsistent verdict
exit 0
```

All 18 (opcode, pair) combinations reach a positive verdict, the base and head
responses are byte-identical on all 333 frames, and no frame in `distinct` or
`agree` mode fires the verdict (the script fails if one does, so it pins the
negative direction too).

**Its falsifier does fire.** Tying the shipped module's `alias_inconsistent` low
and re-running gives exit 1 with exactly **162** base/head response mismatches —
one per positive verdict above. That is the AC-4 obligation, discharged against a
suite that can actually see the predicate.

The DEREF pair counts are 8/10/6 rather than 10/10/10 because the script drops
variants whose collision offset would fall outside `[0, 0xFFFFFFFF]` or overflow
`fp + offset` / `base_index + offset`. For DEREF the middle address is
`base_index + offset_b`, so making a alias b requires `offset_b = fp + offset_a -
base_index`, which is out of range for some (fp, base_index) variants. Those
frames are skipped rather than silently wrapped.

## Scope of the claim

This is coverage evidence, not a proof. The unbounded statement — that the
extracted module agrees with the base predicate on the whole input space — is
carried by AC-1 (`check_cell_alias_equiv.sh`), a Yosys SAT miter over all 656
input bits with four non-vacuity perturbations. AC-5 is what pins the extraction
*in the frontend's fault-priority ladder*, which the miter deliberately does not
model.

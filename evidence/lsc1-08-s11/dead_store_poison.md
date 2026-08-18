# LSC1-08 S11 — AC-2: dead-store poisoning

This note records the method, the sentinel choice, the four dead-store results
and the `poison-live-store` falsifier that gives them meaning.

## 1. What is being claimed

S11 deletes four scratch writes from `asic_core/rtl/lsc1_packet_frontend.sv`:

| # | Base line | Statement | Arm |
|---|---|---|---|
| D1 | 879 | `pres_a = frame_payload[26*8 +: 8];` | DEREF |
| D2 | 913 | `pres_a = frame_payload[26*8 +: 8];` | JUMP |
| D3 | 915 | `pres_b = frame_payload[43*8 +: 8];` | JUMP |
| D4 | 917 | `pres_c = frame_payload[60*8 +: 8];` | JUMP |

The claim is that each is *dead*: its only consumer was one of the five static
admission predicates that AC-1 proves unreachable, so removing it changes no
observable behaviour.

`pres_a`/`pres_b`/`pres_c` are procedural `reg`s, not local variables. They
persist across cycle boundaries and are read again in the sequential
compute-completion ladder. A purely intra-arm reading of deadness would
therefore be wrong, and the poisoning below is what closes that gap
empirically.

## 2. Why the deletion is dead — the static argument

The surviving consumers of the three scratch registers are all in the
completion ladder, and each is reachable only from an arm whose write S11
keeps:

- `pres_a` is read by the `C_XOR_SOLVE` / `C_SOLVE` states, which are entered
  only from the XOR/MUL catch-all arm. That arm's own write to `pres_a` (base
  `:968`) is **not** deleted.
- `pres_b` and `pres_c` are read by `C_DEREF_POINTER` / `C_DEREF_VALUE`, which
  are entered only from the DEREF arm. The DEREF arm's writes at base `:882`
  and `:884` are **not** deleted.
- The JUMP completion states `C_JUMP_INVERSE` → `C_JUMP_PC` → `C_JUMP_FP` read
  none of `pres_a`/`pres_b`/`pres_c`.

So the JUMP arm's three writes (D2/D3/D4) fed only P3, and the DEREF arm's
`pres_a` (D1) fed only P2. All four consumers are exactly the predicates AC-1
proves the validator dominates. There is no hierarchical or cross-module
reference to these registers anywhere in the repository.

## 3. Method

The static argument above is an argument, not a receipt. AC-2 turns it into
one by *poisoning*: rather than deleting the write and hoping nothing noticed,
each removed write's target is clobbered with an adversarial constant at the
top of the arm where the write used to live, and the full frontend simulation
gate is re-run.

If any downstream logic still observed the register, the poison propagates and
the gate goes red.

### Sentinel choice: `8'hA5`

`8'hA5` = 165 is adversarial for this specific slice, not arbitrary:

- It is `> 1`, which is exactly the malformed presence encoding that every one
  of the deleted predicates tested for. A surviving reader that still applied
  a `> 1` test would fire immediately.
- Its low bit is set, so it is also truthy under the `!pres_x` half of the
  `(!pres_x && val_x != 0)` disjunct — it cannot accidentally land on the
  benign side of either half of the predicate.
- It is not `0`, `1`, `8'hFF` or any other value the surrounding RTL treats
  specially, so a green result cannot be explained by the value happening to
  coincide with a legitimate encoding.

The poison is applied at the *top of the arm*, i.e. in the same procedural
position the deleted write occupied, so cycle-accurate timing of the scratch
register is unchanged.

## 4. Results

All runs are `make -C test/packet_frontend sim` on a scratch copy of the head
tree. Neither poisoned tree is committed.

### 4.1 The four dead stores — poisoned together

All four targets clobbered with `8'hA5` simultaneously (the strictly harder
case than poisoning them one at a time):

```
exit 0 — 12 pass markers, identical marker set to base
```

The gate does not notice. Consistent with the four writes being dead.

### 4.2 Named falsifier `poison-live-store`

The same technique applied to a **surviving, live** write — DEREF
`pres_b = frame_payload[47*8 +: 8];`, which S11 keeps:

```
exit 2
FATAL: tb_deref_retire_trace.sv:57: result CRC mismatch got=00000000
```

The gate goes red on the first DEREF retire trace. This is what makes §4.1
informative: the poisoning method demonstrably *can* detect a live store in
exactly this register, in exactly this arm, with exactly this sentinel. The
green result in the dead case therefore carries information rather than
reflecting a blind harness.

> Scope line-number correction: the scoping document cites the live DEREF
> `pres_b` store at base `:881`. The actual base line is `:882`; `:881` is
> `base_index = frame_payload[43*8 +: 32];`. The byte-exact anchor string
> `pres_b = frame_payload[47*8 +: 8];` occurs exactly once and is unambiguous,
> so the falsifier targets the intended statement. The off-by-one is in the
> scope's line citation only, not in the identification of the store.

## 5. Boundedness

This establishes deadness **with respect to the existing directed and
constrained-random frontend suite**, not universally. It is a bounded check
and is labelled as such throughout the receipt. It is **not** a proof of
dead-store elimination, and no unbounded or sequential-equivalence claim is
made on its basis.

The unbounded component of this slice is AC-1 alone, which is a complete SAT
proof over the validator's whole 1547-bit input space and which is what
establishes that the four writes had no *reachable* consumer in the first
place. AC-2 is the empirical cross-check on that argument, not its foundation.

# M0 manager ledger

## Scope and gate

M0 is repository-baseline work only: provenance, reproducible verification,
and the semantic-profile gate.  It does **not** authorize an RTL controller.
The controller gate is: an executable semantic profile reviewed and merged,
then M0 green on the pinned toolchain.

## Status

| Item | Owner | Status | Evidence / exit criterion |
|---|---|---|---|
| Seed inventory and frozen-source audit | manager | complete | `results/m0-20260724T200511Z/audit.log` |
| Reproducible commands and versions | manager | complete | `results/m0-merge-20260724T210000Z/` |
| M0 verification suite | manager | complete | all six M0 commands pass at `8e1de43`; GF(2^8) is a 32-frame bounded BMC proof |
| Written semantic profile | semantic-profile owner (unassigned) | blocked | executable profile reconciles Rust interpreter and prose |
| RTL controller | unassigned | gated | prohibited until prior row is merged and M0 green |

## Repository audit

The seed contains 53 tracked files at `edc2357c558ef42392a7aafc5e34bb7688e7def1`.
The frozen upstream checkout is `leanEthereum/leanVM-b` at
`c308034ab78619b39a59d26f3dc60e7df5b52649`; the five files named in
`docs/SOURCE_AUDIT.md` were inspected from that checkout.

Verified facts: the interpreter uses `u32` instruction offsets/PC/FP; field
bytes are little-endian polynomial coefficients; multiplication by `x` folds
with `0x87`; XOR/MUL support one-missing-input deduction; `DEREF` reconciles
write-once cells; and access counts are advanced even for all JUMP reads.

Seed claims remain hypotheses until the logs and profile support them. The
M0 audit found that `make check` regenerates tracked design-space reports, so
verification records the post-run diff; the historical `SHA256SUMS` is a seed
snapshot, not an integrity check for future M0 artifacts.

M0 corrected two executable seed defects: `Makefile` now uses configurable
`python3` by default, and the formal harness declares `multiclock on`. Its
32-step check is now explicitly bounded BMC; it must not be presented as an
unbounded induction proof.

The historic SBY/cvc5 invocation reached assertion frame 21 but did not
discharge it within a deterministic cap.  The current `gf8_mul.sby` instead
uses ABC `bmc3`, which bit-blasts the unchanged symbolic-input harness and
discharges all 32 frames inside the same 45-second cap.  This is a sound
bounded result, not an unbounded induction proof.  The earlier CVC5,
Boolector, and Z3 outcomes are retained as diagnostic evidence only.

## Dependency graph and ownership

```text
frozen upstream sources ──> semantic profile ──> controller authorization
                            ^
toolchain capture ─> M0 checks ─> M0 green ────┘
```

| Path | Owner | Change rule |
|---|---|---|
| `docs/M0_MANAGER.md`, `results/` | manager | M0-only evidence and decisions |
| `docs/SEMANTIC_PROFILE.md` | semantic-profile owner | must cite frozen Rust/prose behavior |
| `src/` | RTL owner | no controller work before gate |
| `sim/`, `formal/`, `lean/` | verification/formal owners | changes require an independent test |
| `test/`, `tools/` | verification owner | preserve reproducibility |

## Milestone plan

1. M0: pin and execute the baseline toolchain; publish audit/logs (this PR).
2. Semantic profile: resolve executable interpreter versus prose and define
   conformance vectors.
3. M1: simulation-only wide-port controller against that profile.
4. M2+: byte RPC, memory services, DEREF/trace, then BLAKE3.

## Semantic blockers

1. `DerefMode` prose/comment says `pc + gamma`; frozen interpreter writes
   `g^(pc + 2)`.  The executable behavior is the provisional reference.
2. Full XOR/MUL require write-once back-solving; MUL needs nonzero division.
3. DEREF has deferred equality and bidirectional filling, not load/store.
4. JUMP reads/counts three cells whether or not taken; targets require a
   verified `g^i -> i` resolver.
5. The full hardware/service protocol is draft only and has no merged
   executable semantic profile.

## Decision log format

Append entries as: `YYYY-MM-DD | ID | decision | evidence paths + upstream
lines/commit | owner | consequence | revisit trigger`.

| Date | ID | Decision | Evidence | Consequence |
|---|---|---|---|---|
| 2026-07-24 | M0-001 | Freeze semantics at the supplied upstream commit. | `docs/SOURCE_AUDIT.md`; upstream checkout | Do not infer behavior from moving `main`. |
| 2026-07-24 | M0-002 | Do not begin controller RTL. | semantic blockers above | Controller remains gated. |
| 2026-07-24 | M0-003 | Use bounded, multi-clock BMC for the existing harness. | `results/m0-merge-20260724T210000Z/formal-sby.log` | ABC `bmc3` proves all 32 configured frames; this is not an unbounded claim. |
| 2026-07-24 | M0-004 | Retain alternate-engine observations as diagnostics, while the required SBY invocation uses ABC BMC. | `results/m0-gf8-bounded-20260724T203611Z/`; `results/m0-merge-20260724T210000Z/` | Historical CVC5/Z3 timeouts and Boolector incompatibility do not represent the current required check. |
| 2026-07-24 | M0-005 | Merge current `main` with a normal merge commit and rerun every M0 command. | `8e1de43`; `results/m0-merge-20260724T210000Z/` | PR remains linear-history-safe (no rebase/force-push); M0 is green at this head. |

## Reproducible results

The current merged-head run lives under `results/m0-merge-20260724T210000Z/`:
`run.sh` is the exact driver, `versions.log` records tool versions, and one
`*.log` file is produced per command.  Logs are intentionally retained as
review evidence.

The GF(2^8) diagnosis is separately recorded in
`results/m0-gf8-bounded-20260724T203611Z/`. Its executable `run.sh` captures
the short capped original SBY/cvc5 baseline, Z3 and Boolector diagnostic
settings, the passing depth-22 finite SAT run, elaboration, complete stdout and
stderr, versions, and exit statuses.

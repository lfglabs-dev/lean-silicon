# Current-candidate frozen-oracle evidence

This record was run against candidate source commit
`0a4fe71e61ceed301333bd90d78f36583a347150` before this evidence-only commit.
The final PR head adds only this record; the implementation and all tested
source files are the stated tested head. No Actions run/job URL was available
when this local record was created.

The frozen oracle checkout was `leanEthereum/leanVM-b` at
`c308034ab78619b39a59d26f3dc60e7df5b52649`, detached and clean both before
and after each differential. The checker creates its probe in a disposable
detached worktree, invokes `cargo +1.88.0 run --locked`, and removes that
worktree before postflight verification. The frozen upstream `Cargo.lock`
SHA-256 is `0dd4d59866ce12d9bdad27ad7bb3532519a17387821741f52d2c9a43519280c6`.

| Gate | Exact command | Exit status | Result |
|---|---|---:|---|
| scalar differential | `PATH=/workspaces/mission-1c84bcf5/.cargo/bin:$PATH python3 tools/frozen_upstream_differential.py --upstream /workspaces/mission-24ee4121/frozen-upstream --seed 0xC308034A --cases 64 --record /tmp/reviewer-pr7-final-scalar.log --evidence /tmp/reviewer-pr7-final-scalar.json` | 0 | 64 deterministic scalar cases passed |
| M2 differential | `PATH=/workspaces/mission-1c84bcf5/.cargo/bin:$PATH python3 tools/m2_rtl_differential.py --upstream /workspaces/mission-24ee4121/frozen-upstream --seed 0xC308034A --cases 64 --record /tmp/reviewer-pr7-final-m2.json` | 0 | 64 Cargo-vetted RTL XOR/MUL vectors plus controller edge regression passed |
| Python/structural checks | `make check` | 0 | passed |
| RTL simulation | `make sim` | 0 | passed |
| bounded formal | `make formal` | 0 | passed |
| Lean libraries | `make lean` | 0 | passed (existing linter warnings only) |
| boundary rejection | see `boundary-rejection.log` | 0 | dirty candidate plus dirty, attached, and wrong-SHA upstream fixtures each rejected with checker exit 1 |

The scalar gate is intentionally limited to a seven-step straight-line
profile: SET, SET, XOR, MUL, DEREF(Pc), DEREF(Fp), and a non-taken JUMP,
checking cycle count and final cells 0..7. It does not establish full scalar
or upstream equivalence. BLAKE3, Cell DEREF/deferred reconciliation, taken
jumps, allocation hints, and overflow behavior are outside it. The M2 gate
only covers its implemented XOR/MUL controller boundary; it makes no claim
about full upstream execution, pointer resolution, write-once memory, or
trace equivalence.

`scalar.json` and `m2.json` carry the machine-readable command/profile,
exact tested head, clean/detached upstream pre/postflight data, toolchain,
exit status, seed/case count, and source checksums. `SHA256SUMS` checks all
committed evidence inputs and logs.

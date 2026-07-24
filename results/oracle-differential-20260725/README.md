# Frozen upstream differential evidence

This directory retains the command output and input profile for the independent
scalar oracle differential run.  It is reproducible with a checkout of
`leanEthereum/leanVM-b` at the SHA recorded in `differential.log`:

```sh
git clone https://github.com/leanEthereum/leanVM-b.git /tmp/leanvm-b
git -C /tmp/leanvm-b checkout c308034ab78619b39a59d26f3dc60e7df5b52649
python3 tools/frozen_upstream_differential.py --upstream /tmp/leanvm-b --seed 0xC308034A --cases 64 --record results/oracle-differential-20260725/differential.log
```

The probe only covers the deterministic seven-step straight-line profile:
SET, SET, XOR, MUL, DEREF(Pc), DEREF(Fp), and a non-taken JUMP.  It compares
cycle count and memory cells 0..7.  BLAKE3, allocation hints, deferred Cell
DEREF, taken jumps, and unchecked-overflow behavior are out of scope.

`upstream-attempt.log` and `upstream-attempt.status` are retained evidence from
this implementation environment. The pinned checkout was verified, but the
attempt cannot compile because the image lacks `cargo`; this run does not claim
a passed equivalence result.

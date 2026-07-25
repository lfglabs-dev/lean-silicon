# Host runtime and lean_compiler integration evidence

Unfiltered command output for the Mac-side LSC-1 host runtime scaffold
(`host/`), the frozen-compiler export tool and the upstream comparison.

Tested source: `tested-source-head.txt`. Toolchain and the upstream checkout
SHA used for the live runs: `toolchain.txt`.

| Log | Command | Exit |
|---|---|---|
| `make-check.log` | `make check` | `make-check.status` |
| `host-comparison-recorded.log` | `make host-comparison` | `host-comparison-recorded.status` |
| `host-comparison-live.log` | `make host-comparison LEANVM_B_UPSTREAM=/tmp/leanVM-b` | `host-comparison-live.status` |
| `scalar-differential.log` | `make scalar-differential LEANVM_B_UPSTREAM=/tmp/leanVM-b` | `scalar-differential.status` |

`comparison.json` is the `leansilicon.host.comparison/1` document from the
live run: every prepared transaction with its pc, fp, opcode, effective
addresses, input cell presence and values, writes, branch, deferred events,
status, retirement sequence and lane cycle count, plus the final state and the
comparison verdict.

## What this run establishes

Against `leanEthereum/leanVM-b` at
`c308034ab78619b39a59d26f3dc60e7df5b52649`, compiled with `cargo +1.88.0
--locked` in a disposable detached worktree of a clean checkout:

- the frozen `lean_compiler` compiles `host/fixtures/assert_set_xor_mul.zkdsl`
  to the 16-slot bytecode recorded in the checked-in artifact, live and
  reproducibly;
- driving the first 12 of those instructions through the executable LSC-1
  endpoint as host-prepared transactions produces exactly the final memory the
  frozen `Program::execute` produces, for all 12 cells that run touched;
- the independent scalar-oracle differential from the previous lane still
  passes at the same commit in the same environment.

## What this run does not establish

- **Not full-program equivalence.** The fixture's terminating `JUMP` is not
  integrated, so the host executes a 12-step prefix of a 13-cycle upstream run.
  `cycles` is therefore explicitly not compared, and the comparison document
  records that under `comparison.not_compared`.
- **No per-step comparison against upstream.** `Execution::trace` is
  `pub(crate)` at the frozen commit, so `Program::execute` exposes no per-step
  rows. Every per-step field of the schema is emitted with an explicit reason
  for being unverified. The leanSilicon side of those fields is fully recorded;
  the upstream side does not exist to compare against.
- **No official zkDSL validation.** One hand-written fixture is not the
  official program suite, and nothing here claims that milestone.
- **Nothing about RTL.** The endpoint driven here is the executable protocol
  model in `sim/lsc1_transaction.py`. No RTL, netlist, bitstream or silicon was
  exercised, and no formal-verification claim is made or advanced.
- **DEREF, JUMP and BLAKE3 are not driven.** They stop a run with an explicit
  unsupported reason rather than being skipped.

## Reproducing

```sh
git clone https://github.com/leanEthereum/leanVM-b.git /tmp/leanVM-b
git -C /tmp/leanVM-b checkout c308034ab78619b39a59d26f3dc60e7df5b52649
make check
make host-comparison LEANVM_B_UPSTREAM=/tmp/leanVM-b
make scalar-differential LEANVM_B_UPSTREAM=/tmp/leanVM-b
```

The export and live-comparison paths refuse to run against an upstream
checkout that is not a clean detached checkout of the frozen commit, and refuse
to run at all from a dirty candidate tree.

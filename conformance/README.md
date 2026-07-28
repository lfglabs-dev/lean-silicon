# Frozen conformance corpus

`corpus-v1.json` is the unified, immutable LSC-1 conformance corpus for the
first post-G1 lane. It binds protocol bytes and state transitions to frozen
leanVM-b commit `c308034ab78619b39a59d26f3dc60e7df5b52649`.

Every case contains:

- a stable `case_id` and SHA-256 fingerprint over the canonical JSON case
  excluding the fingerprint field;
- exact request and response bytes;
- initial and final endpoint state;
- the decided scalar transition, where one exists;
- complete RETIRE request, response, CRC, sequence, committed state, and DONE
  metadata, or an explicit non-retiring record;
- an upstream comparison mode.

`program_execute` cases are run through the reviewed Rust adapter compiled
inside a disposable worktree of the exact frozen upstream source.
`protocol_only` is deliberate: malformed frames and lane controls do not have a
`Program::execute` representation. Infrastructure failures (checkout,
toolchain, Cargo, adapter I/O) exit 2; semantic mismatches exit 1.

The corpus is immutable by version. Do not edit `corpus-v1.json` by hand. Change
the generator and regenerate it; any semantic change requires a new schema and
corpus version rather than rewriting v1 after release.

```sh
python3 tools/generate_conformance_corpus.py
python3 tools/conformance_differential.py --validate-only
PATH="$HOME/.cargo/bin:$PATH" \
  python3 tools/conformance_differential.py --upstream ../leanVM-b
```

The upstream checkout must be clean, detached, have the canonical origin, and
be at the frozen commit before and after the run. The runner never changes it:
the adapter is copied only into a disposable detached worktree and Cargo uses
the committed lockfile with `--locked`.

# Frozen conformance corpus

`corpus-v2.json` remains the immutable scalar LSC-1 conformance corpus for the
first post-G1 lane. It binds protocol bytes and state transitions to frozen
leanVM-b commit `c308034ab78619b39a59d26f3dc60e7df5b52649`.

`corpus-v1.json` and `schema-v1.json` remain frozen for existing consumers.
Version 2 adds the corrected complete and partial transaction-ID length-fault
vectors; new consumers should use `corpus-v2.json` with `schema-v2.json`.

`corpus-v3.json` is a separate, additive BLAKE3 service-lifecycle corpus. It
freezes the merged software boundary at lean-silicon base commit
`3beb2cb7da772f3c819c8055249c787ea92185d1`: BLAKE3_REQUEST,
SERVICE_REQUIRED, SERVICE_RESPONSE, RESULT, and RETIRE, including the 122-byte
internal service payload and the 131/53-byte host envelopes. It also freezes
rejection evidence for wrong transaction ID, service ID, kind, digest, and
metadata binding, plus replay, abort, and reset. Versions 1 and 2 are not
regenerated or edited by the v3 tooling.

Generate and validate v3 exactly with:

```sh
python3 tools/generate_conformance_corpus_v3.py
python3 tools/conformance_service_lifecycle_v3.py --validate-only
```

The v3 validator checks the JSON Schema, case inventory, fingerprints, byte
lengths, and byte-for-byte deterministic regeneration. The existing
`tools/conformance_differential.py` intentionally remains the frozen v2 scalar
upstream differential; it is not a BLAKE3 lifecycle validator.

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

The corpus is immutable by version. Do not edit a published corpus by hand.
Change the generator and publish a new matching schema/corpus version for every
semantic change. The regression suite pins the frozen v1 artifact digests as
well as reproducing the current v2 corpus from the generator.

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

The v3 claim is limited to the executable Python endpoint/host boundary and
the recorded bytes. It makes no RTL, FPGA, netlist, BLAKE3 datapath,
LSC-1micro, ASIC fetch/memory, or protocol-v1-extension claim, and it does not
change SET, XOR, MUL, DEREF, or JUMP behavior.

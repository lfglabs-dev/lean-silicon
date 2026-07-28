# LSC-1 Phase-B2 capability-contract evidence

Baseline independently verified before edits:
`fda85f5efc6f5b460d72204b4d9c0d882960ec29`, tree
`df42a6211828d856e9a21ba61ecc2cd1b9dc4e71`.

The correction narrows the Phase-B advertised device capability to
`INTERPRETER_COMPAT` (`0x00000002`), matching the packet RTL. The model retains
its broader semantic-oracle profiles, while the model/RTL differential drives
the supported Phase-B profile and the RTL bench/mutation test drives the
unadvertised `FORWARD_ONLY` rejection.

| Check | Exit | Duration | Artifact SHA-256 |
| --- | ---: | ---: | --- |
| official BLAKE3 differential | 0 | 1426 ms | `42b629a692f30c9bfb0fcff81a5eb4631efb576c1355485035dd6d8c50131631` (`blake3_official.log`) |
| repository Python suite | 0 | 11544 ms (288 tests) | `3f3a9d48fd3bfa56895994fed2a415312f4713bb6acbe81144ec9c2ab15f8757` (`python_full_final.log`) |
| model/RTL differential | 0 | 1110 ms | `d13aeaee319cce423e3c559504b2eff9e89be80f067b0a946a7c2edea31bd59e` (`model_final.log`) |
| bounded RTL simulation | 0 | 129 ms | `881d0c9e93dd2f29354bf42351533bfe1b571eb3f4e4f0198d92dc51fe4c064f` (`rtl_final.log`) |
| mutation regression | 0 | 400 ms | `73a36fd9d3c0bd6c193ab3bcfd546574a9f3b2945298b7589aa10584725877c2` (`mutation_final.log`) |
| RTL-to-netlist synthesis (`timeout 900s`) | 0 | 447965 ms | `57b603f2145f71ea57f6830108696d4e030530235d3cecf5d7070036c3021b98` (`netlist_900.log`) |

Rust was available through `/root/.cargo/bin` once `CARGO_HOME=/root/.cargo`
and `RUSTUP_HOME=/root/.rustup` were set; it was not available on the default
PATH. The official test is consequently an executed result, not an environment
blocker.

Synthesis produced `lsc1_packet_frontend.netlist.v` (SHA-256
`bea4db3161ea6fe410e47e9a8573aa07081b26666a702ee37828eae50ab3869f`).
Sequential equivalence was then attempted only against that exact netlist. The
first command failed at setup (exit 1, 2222 ms; `equivalence.log`) because the
gold RTL still contained processes/memories. The corrected command lowered
them first, but found 5039 unproven `$equiv` cells and no SAT model for the
unflattened receiver, transmitter, adapter, and field-encoder submodules. It
was stopped after 585606 ms (exit 143; `equivalence_retry.log`) rather than
claiming a proof. Thus there is no RTL/netlist equivalence result; the precise
missing repository capability is a release sequential-equivalence harness with
the required flattening/state correspondence and reset assumptions.

Every command and status is retained beside its log. This evidence is a
committed handoff artifact, not a claim that the planned release equivalence
gate passed.

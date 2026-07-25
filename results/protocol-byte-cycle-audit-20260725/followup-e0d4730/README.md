# PR #3 reset/DONE follow-up gate evidence

Commit under test: `e0d473054dc4aa909bab8d79cc7db7e5cd89f601`.

All commands below exited `0`; their unedited stdout/stderr is retained in
the sibling log file.

| Command | Exit | Evidence |
|---|---:|---|
| `make check` | 0 | `make-check.log` |
| `make sim` | 0 | `make-sim.log` |
| `make lean` | 0 | `make-lean.log` |
| `make formal` | 0 | `make-formal.log` |
| `yosys -p 'read_verilog -sv src/gf2n_mul_bitstream.sv src/gf128_mul_bitstream.sv src/leanvm_b_stream_alu.sv src/tt_um_leanvm_b_mincore.sv; hierarchy -check -top tt_um_leanvm_b_mincore; proc; check; synth -top tt_um_leanvm_b_mincore; stat'` | 0 | `yosys-lint-synth.log` |

The formal command is the repository's bounded GF(2^8) job.  These logs do
not claim protocol/controller formal verification or exhaustive coverage.

# Protocol byte/cycle audit evidence

The logs in this directory are unfiltered stdout/stderr captured while testing
source commit `4269243cbee893619a6892b01d789b4c816abb22`, recorded again in
`tested-source-sha.txt`.  This evidence commit only adds these logs and this
README; it does not alter the tested implementation.

| Gate | Exit record | Full log |
|---|---|---|
| Python, analytical, and structural checks | `make-check.status` | `make-check.log` |
| SystemVerilog simulation | `make-sim.status` | `make-sim.log` |
| Lean default and explicit library targets | `make-lean.status` | `make-lean.log` |
| Bounded GF(2^8) SymbiYosys job | `make-formal.status` | `make-formal.log` |
| CI Yosys hierarchy/check/synthesis invocation | `yosys-lint-synth.status` | `yosys-lint-synth.log` |

All recorded commands exited zero.  The SymbiYosys result is a bounded job
specified by `formal/gf8_mul.sby`; these logs are not evidence of a proof of
the byte-lane protocol or of the full controller.

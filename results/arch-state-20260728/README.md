# Registered architectural-state milestone — blocked before full refinement

This receipt is for the explicit `arch_*` observation interface introduced at
the same source revision. It is not a release-equivalence PASS and makes no
ASIC-readiness claim.

## Completed, non-vacuous milestone

`reset-idle.log` records Yosys 0.33 proving the parser partition's reset
establishment obligation (`SAT proof finished - no model found: SUCCESS`). The
bound is three sequential steps; the obligation has four reset assertions and
one reset input constraint. `interface-coverage.log` records 47 mapped fields
and all six packet output channels. The mapping checker includes a source-map
mutation guard. `rtl.log`, `differential.log`, and `mutation.log` are the
focused regression gates; their SHA-256 values are in `SHA256SUMS`.

## Exact current blocker

The next smallest unclosed obligation is **frontend idle/composition**:

```
R(frontend_rtl, arch) && idle(arch) && no_accept && !abort
    => R(frontend_rtl', arch_transition(arch, inputs))
```

The repository's existing executable LSC-1 model is Python transaction logic,
not a synthesizable one-cycle transition relation. It has no representation of
the RX/TX backpressure, ALU, or field-encoder intermediate registered phases.
Consequently, supplying an unconstrained `arch_transition` here would be the
forbidden symbolic bridge; deriving it by peeking into RTL would merely restate
RTL and would not establish refinement to the executable model. The bounded
parser reset proof is sound but does not discharge this frontend obligation.

The required next architectural artifact is a reviewed, executable clocked
LSC-1 architecture transition module (including parser/TX stutter semantics),
or a reviewed refinement abstraction that relates its transaction steps to
those cycles. Until it exists, command-family, all-phase, and full sequential
equivalence milestones are deliberately marked BLOCKED rather than run as a
larger flat timeout. Capability `0x00000002` and forward-only rejection
`BAD_PROFILE=0x86` remain tested by the differential and RTL regressions.

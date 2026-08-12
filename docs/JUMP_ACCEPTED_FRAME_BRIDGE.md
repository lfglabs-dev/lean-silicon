# JUMP accepted-frame lifecycle

This lane proves one canonical not-taken JUMP (`0x07`) from its complete
accepted LSC-1 v1 request envelope through a byte-exact RESULT and a matching
RETIRE. The production frontend accepts all 113 request bytes, emits exactly
the expected 27-byte payload in a 36-byte RESULT envelope, and derives the
RETIRE checksum from those payload bytes. The witness uses transaction 1,
`pc = fp = 0`, offsets `(0, 1, 2)`, canonical absent cells, and the interpreter
profile. Its RESULT payload CRC-32 is `0x34ec07fd`; matching retirement commits
`pc = 1`, preserves `fp = 0`, increments `retire_seq` once, clears the pending
result, and emits one completion pulse.

Executable RTL records request acceptance at cycle 114, the last RESULT byte
at cycle 151, matching RETIRE acceptance at cycle 171, and the first and only
completion at cycle 172. Registered capture and formal sampling put the stable
post-RESULT checkpoint at the last step of depth 155, matching commit at the
last step of depth 175, and final quiescence at the last step of depth 176.
Each reachability task is paired with an independently checkable safety task;
the below-bound check reruns each cover one step earlier and requires failure.
These bounds are not widened by this lane.

The depth-20 `safety` task retains arbitrary traffic and backpressure. Longer
tasks use the same byte-exact environment but are decomposed into
`accepted_result`, `matching_retire`, and `post_retire` obligations. BTOR and
`btormc` check the fixed witness and same-depth assertions; SMTBMC/Boolector is
used only for shallow arbitrary-traffic safety. Every solver subprocess has a
540-second fail-closed timeout, inside the 600-second outer job bound.

Critical RESULT-envelope, payload-CRC, early-publication, stage-retention,
duplicate-retirement, and retained-completion mutations run only against the
first sub-goal that can observe them. A pristine baseline must pass first, and
only a completed assertion failure counts as a kill. Missing covers, solver
timeouts, or tool errors fail the mutation gate. The executable differential
suite separately kills the established JUMP inverse-width mutation.

`LeanVMBMinCore.AcceptedJump.accept` validates the complete envelope with the
production reflected IEEE CRC-32, decodes exactly 103 payload bytes, and feeds
the existing `preparedJumpDecision`; it introduces no alternate JUMP
semantics. The accepted-effect theorem derives RETIRE CRC from the effect's
actual result payload and applies the existing exactly-once transaction
theorem. A concrete accepted-frame theorem supplies non-vacuity, while CRC,
branch-byte, result-byte, and dropped-premise mutations establish sensitivity.

This is finite full-profile, authored-RTL assurance. It is not an unbounded
liveness proof, a proof under unfair backpressure, an import of SystemVerilog
into Lean, RTL-to-netlist equivalence, a physical-netlist proof, or silicon
evidence. The separately established JUMP preparation rules—including taken
branch target and inverse validation—remain outside this single not-taken
lifecycle witness. BLAKE3 service refinement is also outside this lane.

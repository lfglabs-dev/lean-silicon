# Lean proof-foundations evidence

Parent and tested API boundary: `40199b377ecc80115faa5a7331048b522a1f425f`
(merged protocol PR #3).  This evidence intentionally excludes open PR #5 and
does not inspect, import, or prove claims about its RTL.

Scope added by this change is `LeanVMBMinCore.CheckedIndex`: the frozen strict
profile's executable `u32` checked addition and small reusable lemmas about
success, overflow, local-address results, and PC increments.  It is a proof
foundation only; it does not claim full scalar-machine or RTL verification.

The final command outputs and exit codes are retained alongside this file.
The repository's project gate is also run to reject `sorry`, `admit`, and
`axiom` in Lean sources.

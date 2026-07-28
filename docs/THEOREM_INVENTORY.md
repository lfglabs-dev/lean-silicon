# Lean theorem inventory

This inventory records the public correctness surface of the v1
packet/transaction foundation. All declarations are kernel-checked by the
pinned Lean toolchain. They are functional-model results only; the limits in
`PROOF_BOUNDARIES.md` apply.

## `LeanVMBMinCore.Packet`

| Declaration | Meaning |
| --- | --- |
| `decode_encode_request` | A canonical request encoded with any checksum function decodes to the same request. |
| `decode_encode_response` | A response encoded with any checksum function decodes to the same response. |
| `bad_sof_precedes_other_request_errors` | A wrong request SOF is reported before later envelope checks. |
| `bad_version_precedes_request_flags_length_checksum` | After a valid SOF, a wrong version is reported before flags, length, and checksum checks. |

The module also contains executable request and response round-trip examples.
The checksum parameter is a stable refinement seam, not a claim that CRC-32
has already been proved correct.

## `LeanVMBMinCore.Transaction`

| Declaration | Meaning |
| --- | --- |
| `stage_is_atomic` | Successful staging does not change committed architectural state. |
| `abort_preserves_committed` | Abort does not change committed state. |
| `abort_clears_pending` | Abort returns the transaction state to idle. |
| `matching_retire_commits` | A matching transaction id and result checksum commits next PC/FP, increments the retirement sequence, and returns idle. |
| `matching_retire_is_exactly_once` | Repeating an already accepted RETIRE cannot commit again and reports `badState`. |
| `mismatched_retire_does_not_commit` | A mismatched RETIRE abandons the staged transition without changing committed state. |
| `reset_restores_initial` | Reset restores the complete initial model. |

The module also contains executable stage/retire and stage/abort examples.
Later arithmetic and DEREF/JUMP lanes can produce `Transition` values without
changing this lifecycle interface.

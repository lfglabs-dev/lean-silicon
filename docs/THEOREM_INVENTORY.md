# Lean theorem inventory

This inventory records the public correctness surface of the v1
packet/transaction foundation. All declarations are kernel-checked by the
pinned Lean toolchain. They are functional-model results only; the limits in
`PROOF_BOUNDARIES.md` apply.

## `LeanVMBMinCore.Packet`

| Declaration | Meaning |
| --- | --- |
| `decode_encode_request` | A protocol-sized canonical request encoded with any checksum function decodes to the same request. |
| `decode_encode_response` | A protocol-sized response encoded with any checksum function decodes to the same response. |
| `bad_sof_precedes_other_request_errors` | A wrong request SOF is reported before later envelope checks. |
| `oversized_request_precedes_checksum_and_header_errors` | After a valid SOF, a declaration above the 256-byte cap is rejected at the header. |
| `bad_checksum_precedes_request_version_flags_and_payload_length` | For an in-cap request after a valid SOF, a bad checksum is reported before version, flags, and payload-length checks. |
| `bad_version_precedes_request_flags_and_payload_length` | After SOF, cap, and checksum validation, a wrong version is reported before flags and payload-length checks. |

The module also contains executable request and response round-trip examples.
The checksum parameter is a stable refinement seam, not a claim that CRC-32
has already been proved correct.

## `LeanVMBMinCore.Transaction`

| Declaration | Meaning |
| --- | --- |
| `stage_is_atomic` | A valid stage succeeds with no fault, preserves committed state and `stateValid`, and enters `resultPending` with exactly the proposed transition. |
| `out_of_range_stage_is_rejected` | A stage whose current PC or FP is outside the v1 index range is rejected without changing the model. |
| `state_mismatch_precedes_index_range` | A staged transition that disagrees with valid committed PC/FP reports state mismatch before its current-index range is considered. |
| `abort_preserves_committed` | Abort does not change committed state. |
| `abort_clears_pending` | Abort returns the transaction state to idle. |
| `matching_retire_commits` | A matching transaction id and result checksum commits next PC/FP, increments the retirement sequence, and returns idle. |
| `matching_retire_is_exactly_once` | Repeating an already accepted RETIRE cannot commit again and reports `badState`. |
| `mismatched_retire_does_not_commit` | A mismatched RETIRE abandons the staged transition without changing committed state. |
| `reset_restores_initial` | Reset restores the complete initial model. |

The module also contains executable stage/retire and stage/abort examples.
Later arithmetic and DEREF/JUMP lanes can produce `Transition` values without
changing this lifecycle interface.

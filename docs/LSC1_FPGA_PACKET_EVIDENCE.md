# LSC1-09 physical ULX3S packet evidence

No physical evidence packet is currently committed. The required run is one
fresh-reset, SRAM-only ULX3S v3.1.8 capture containing exactly `STATUS_QUERY`,
`NEGOTIATE`, `SET_CONSTANT(txn=1, pc=0, fp=0, m[2]=3)`, and its CRC-bound
`RETIRE`. Every request and response byte must traverse the existing UART bridge
and 8-bit ready/valid endpoint pins; hierarchical or wide injection is invalid.

`tools/verify_lsc1_fpga_packet_evidence.py DIRECTORY` is the offline acceptance
gate. It binds `capture.json`, `SOURCE_MANIFEST.txt`, the archived bitstream,
the exact captured source commit/tree and its Git blobs (the later evidence
commit is expected to differ), clean build inputs, v3.1.8/85F IDCODE, explicit
UART path, loader/CAD versions, 25 MHz constraint, timestamps, and SRAM-only
programming. It independently replays all four encoded frames through the
executable model and checks the exact initial state, negotiated scalar subset,
SET result, result CRC, and committed RETIRE state.
`SHA256SUMS` must cover every regular evidence file other than itself.
The SET result has exactly one write (`address=2`, `value=3`), no deferred
equalities, and one access entry whose index 0 is address 2.

The verifier tests use a synthetic fixture only to prove rejection behavior.
They do not constitute FPGA, UART, loader, or physical evidence. Exactly one
SET result-value bit, the RETIRED committed-PC bit changing 1 to 0, and one
provenance digest are mutated in separate tests; each must fail in its intended
semantic or provenance category.

The real result directory is reserved as
`results/lsc1-09-s1-ulx3s/`. It must not be created or populated until a board
is observed by USB and JTAG, the exact source-built image is loaded without any
flash option, and the physical capture completes. Build artefacts alone must
never be presented as this packet.

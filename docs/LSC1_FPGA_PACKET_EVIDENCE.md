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
UART path, loader/CAD versions, the 25 MHz board input and PLL-derived 10 MHz
full-LSC1/UART core constraints, timestamps, and SRAM-only programming. The
timing receipt must show that nextpnr recognized both clocks and passed the
10 MHz core constraint. It independently replays all four encoded frames through the
executable model and checks the exact initial state, negotiated scalar subset,
SET result, result CRC, and committed RETIRE state.
Packet-local digests are integrity checks, not self-authenticating provenance.
The verifier therefore also requires the bitstream and the raw Yosys, nextpnr,
timing, and tool-version files to be byte-for-byte equal to the immutable
Git-tracked deterministic build bundle in
`results/ulx3s-lsc1-packet-20260726/`, and requires `source_head` to equal that
bundle's clean input revision. Repeating an arbitrary bitstream digest in
`receipt.json` and `SHA256SUMS`, or independently authoring plausible CAD log
strings, is rejected even when all packet-local checksums are recomputed.
`SHA256SUMS` must cover every regular evidence file other than itself.
The packet must include the raw clean-status string plus `preflight.json`,
`tool_versions.txt`, `timing.txt`, synthesis/route logs, and `load.log`. The
receipt's only accepted load command is `openFPGALoader -b ulx3s BITSTREAM`;
`-f` and every flash option are rejected. `load.log` must independently contain
exactly one `loader-command: openFPGALoader -b ulx3s BITSTREAM` line matching
the receipt and exactly one `loader-exit-code: 0` line; missing, failed, or
contradictory loader records are rejected.
The source manifest must contain exactly the verifier's complete packet build
input set (RTL, wrapper/UART/PLL sources, constraint, build recipe, and helper
scripts), with every digest checked against the pinned Git revision.
The SET result has exactly one write (`address=2`, `value=3`), no deferred
equalities, and one access entry whose index 0 is address 2.

The verifier tests combine the pinned host-build files with synthetic capture,
preflight, loader, and receipt fields only to prove acceptance and rejection
behavior. They do not constitute UART/JTAG activity, loading, FPGA execution,
or physical evidence. Family-level regressions replace the bitstream while
recomputing both attacker-controlled digest layers, and replace nextpnr/timing
receipts with independently authored trusted-looking strings; both families
must fail provenance validation. Separate single-bit semantic and digest
mutations must also fail in their intended category.

This anchoring proves only which host-generated netlist/bitstream and P&R
receipts a future packet names. The executable Python model, Lean sources,
authored RTL, generated build artifacts, place-and-route results, loader
records, and physical hardware observations remain distinct evidence layers.
Nothing here turns bounded checks into unbounded proof, demonstrates that a
board was attached or programmed, or establishes end-to-end execution.

The real result directory is reserved as
`results/lsc1-09-s1-ulx3s/`. It must not be created or populated until a board
is observed by USB and JTAG, the exact source-built image is loaded without any
flash option, and the physical capture completes. Build artefacts alone must
never be presented as this packet.

# ULX3S-85F LSC-1 seed-0 hardware run

Date: 2026-07-26

Board: ULX3S-85F v3.0.8, JTAG IDCODE `0x41113043`

Transport: onboard FT231X UART, 115200 8N1

Repository HEAD before the working-tree implementation: `618b39923862e660589cc6258e258783904b3861`

The newly added ULX3S wrapper was simulated, synthesized with the 2026-07-26
darwin-arm64 OSS CAD Suite, placed/routed for an ECP5-85F CABGA381 at 25 MHz,
and loaded into volatile FPGA SRAM with `openFPGALoader -b ulx3s`. No SPI flash
write was requested.

## Build evidence

- 758 LUT4-equivalents and 396 flip-flops before packing.
- Routed maximum clock frequency: 176.58 MHz; requested frequency: 25 MHz.
- Bitstream size: 290,579 bytes.
- Bitstream SHA-256: `87b204ec01e0ff495b102f0ea6f934033f47c8c8b70f858b67f8c5a908cf5795`.
- `openfpgaloader-sram.txt` records successful SRAM erase, load, and disable-configuration completion.

## Observed exchanges

`exchanges.jsonl` is the direct host-driver record, including raw bytes and
SHA-256 digests. All four operations observed a serial response:

| Operation | Observed response | Result |
|---|---|---|
| STATUS | `01010f08` | exact protocol signature |
| SET128 | `000102030405060708090a0b0c0d0e0f` | PASS |
| XOR128 | `f0` repeated 16 times | PASS |
| MUL128 | `c043248e79cfa802850661cb3c8aed47` | PASS |

The JSONL honestly records `repo_dirty: true`: the run exercised the new
wrapper before it was committed. The recorded HEAD alone is therefore not a
complete source identity; the bitstream digest and current working-tree files
identify this run.

## Scope

This proves the repository's historical MinCore arithmetic seed crossed the
physical UART and exact 8-bit LSC-1 ready/valid boundary on this board. It does
not prove the v1 packet executor, which is not implemented in RTL, and it does
not satisfy the build plan's second-board reproducibility gate.

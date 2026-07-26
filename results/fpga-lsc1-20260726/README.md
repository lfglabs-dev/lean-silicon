# Historical ULX3S-85F LSC-1 physical run

Date: 2026-07-26

This directory preserves evidence from a historical physical run. It does not
replace the maintained ULX3S implementation inherited from PR #16.

## Identity and provenance limits

- The USB product text reported `ULX3S FPGA 85K v3.0.8`.
- The observed PCB is an ULX3S v3.1.8.
- JTAG IDCODE `0x41113043` identifies the LFE5U-85F FPGA, not the ULX3S PCB
  revision. The USB text/observed-PCB discrepancy is unresolved by IDCODE.
- Every exchange records `repo_dirty: true`.
- Recorded repository HEAD
  `618b39923862e660589cc6258e258783904b3861` predates the dirty-tree harness
  implementation and is not, by itself, source provenance.
- The physical bitstream is not committed. Its recorded SHA-256 is
  `87b204ec01e0ff495b102f0ea6f934033f47c8c8b70f858b67f8c5a908cf5795`.
- `candidate-harness.patch` is an exact snapshot of the harness changes later
  committed as `e14902d4ca50c3c58037ad825774f0c160d74ab6`, relative to `618b399...`.
  The surviving run records do not prove that the dirty working tree was
  byte-for-byte identical to this later commit, so it is a **candidate
  reconstruction**, not exact physical-run source provenance.

Consequently this archive does not prove packet-v1, v3.0.8 hardware identity,
reproducibility, binary identity, or clean source-to-bitstream provenance.

## Preserved physical observations

`openfpgaloader-sram.txt` is the original loader log and is preserved verbatim.
It reports a volatile SRAM load; no SPI-flash write is claimed. No hardware
action is needed to validate this archive.

`exchanges.jsonl` is the original five-line host-driver record and is preserved
verbatim. The first and fifth lines are duplicate STATUS observations. Frozen,
independently checked response bytes are:

| Operation | Response | Interpretation |
|---|---|---|
| STATUS | `01010f08` | `pass` is `null`; the four-byte signature matches |
| SET128 | `000102030405060708090a0b0c0d0e0f` | expected bytes match |
| XOR128 | `f0` repeated 16 times | expected bytes match |
| MUL128 | `c043248e79cfa802850661cb3c8aed47` | expected bytes match |

The JSONL-declared request, response, and expected lengths and SHA-256 values
are checked by `fpga_harness/test_fpga_lsc1_evidence.py` against decoded bytes
and a frozen oracle. `EVIDENCE_SHA256SUMS` authenticates the verbatim records
and candidate patch.

## Independent controller replay

The controller replay on the integrated PR #19 head used no board:

- repository checksum gate passed;
- UART simulation passed STATUS/SET/XOR/MUL;
- `make check` passed;
- Linux Yosys 0.33, nextpnr-ecp5 0.6, and ecppack rebuilt the candidate harness;
- nextpnr reported 107.83 MHz maximum frequency at a requested 25 MHz;
- rebuilt bitstream SHA-256:
  `827d6f1e3e429a85035005fdff52057fcba14d96f6b757c9b4240e446ff966fb`.

That rebuilt digest differs from the recorded physical-run digest
`87b204ec01e0ff495b102f0ea6f934033f47c8c8b70f858b67f8c5a908cf5795`.
The replay validates buildability and timing of the candidate reconstruction,
not binary identity with the physically exercised bitstream.

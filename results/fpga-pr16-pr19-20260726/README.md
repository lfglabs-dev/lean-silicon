# PR #16 maintained-bitstream physical follow-up

Date: 2026-07-26

This run used one ULX3S reporting ECP5 IDCODE `0x41113043` (LFE5U-85F).
Every FPGA configuration was volatile SRAM-only through `openFPGALoader -b
ulx3s`; no command used `-f`.

## Exact build identity

- source/input revision: `9d5741961a3851c584fc2882ae7eccd41a1ec404`
- source manifests: `inputs-match-revision: yes`
- smoke SHA-256: `96eb9eda7421bac902eacaeced21eee0db9a80b8f2f2effdb52b515d68e0b2e3`
- UART SHA-256: `efa908bc6b4285d5461a4d6c2c65081ce7063efc7ede080a867ddbde81edde0e`
- smoke post-route Fmax: 291.97 MHz at a requested 25 MHz
- UART post-route Fmax: 161.58 MHz at a requested 25 MHz
- UART was rebuilt twice locally with the same SHA-256.

The hashes previously written in the PR #16 document (`eb3d81...` and
`7272b0...`) did not match its committed bitstreams. This follow-up rebuilt the
exact integrated source and updated the archive and documentation to the bytes
actually tested.

## Physical observations

- JTAG detection returned `0x41113043`, manufacturer Lattice, family ECP5,
  model LFE5U-85.
- The smoke image passed hash verification and was accepted for SRAM loading.
  Its terminal capture ended before the final `Done` line, so only the UART
  image has a complete loader transcript. LED0 cannot be observed from the
  terminal, and no claim is made about its visual state or power-cycle reset.
- The UART image passed hash verification, loaded to 100%, and reported
  `Disable configuration: DONE`.
- STATUS at 1 Mbaud returned exactly `01010f08` before and after a second SRAM
  reload.

Deterministic primitives, including the PR #16 `0x7f` resynchronization byte:

| Case | Request | Response/oracle | Duration |
|---|---|---|---:|
| SET 3 | `7f0303000000000000000000000000000000` | `03000000000000000000000000000000` | 91,592,167 ns |
| SET 5 | `7f0305000000000000000000000000000000` | `05000000000000000000000000000000` | 95,009,500 ns |
| XOR 3,5 | `7f010305` followed by 30 zero bytes | `06000000000000000000000000000000` | 111,193,334 ns |
| MUL 3,5 | `7f02`, little-endian 3, little-endian 5 | `0f000000000000000000000000000000` | 113,665,250 ns |

Every response was complete and byte-for-byte equal to its independent oracle.

## Compiled-program prefix

The refactored PR #19 runner executed the frozen `assert_set_xor_mul` artifact
through PR #16's maintained driver. It completed 12 physical arithmetic
transitions, compared all 12 responses, reproduced memory cells 0 through 11
with no missing address or mismatch, and stopped before bytecode slot 12
because it is JUMP. Result: `PREFIX_MATCH`, not full-program PASS.

The complete generated `program-run.json` is authenticated by
`EVIDENCE_SHA256SUMS` and has SHA-256
`2e1cf626de629936a828ba890eeae4d0177fe87c69bac2eb25012c4c1178af6b`.
It recorded `repo_dirty: true` because the locally rebuilt evidence archive was
present before the transaction; this must not be interpreted as clean-source
provenance.

## Transport robustness

- repeated transactions succeeded throughout the primitive and 12-step runs;
- a deliberately partial `ABORT, SET, 03` request produced one echoed byte and
  then the expected timeout (`expected 16 bytes, got 1`);
- the next resynchronizing STATUS recovered and returned `01010f08`;
- unknown opcode `55` produced exactly the stale error byte `e0`, which was
  drained before the next transaction;
- closing and reopening the host port preserved a correct STATUS response;
- reloading the exact UART image in SRAM restored a correct STATUS response;
- the host runner commits no VM destination until a full response has passed
  its oracle comparison, covered by its deterministic mismatch/timeout tests.

## Unperformed manual observations

The terminal cannot observe LED0 or physically remove board power. Therefore
the LED pattern and disappearance of SRAM configuration after a real
power-cycle remain explicitly unverified here.

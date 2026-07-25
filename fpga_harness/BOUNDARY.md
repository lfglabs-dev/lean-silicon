# Pin-accurate harness boundary

The rule, stated once: **every byte the harness exchanges with LSC-1 crosses the
8-bit ready/valid pin interface, one byte per accepted beat.** There is no second
path. A harness that moves a 128-bit operand into the core as a 128-bit signal
is not a harness of this ASIC, it is a different device that happens to contain
the same arithmetic.

This document is normative for `fpga_harness/`. `boundary_check.py` enforces the
mechanically checkable parts of it in `make check`.

## The exact boundary

The boundary is the port list of `lean_silicon_lsc1`
(`asic_core/rtl/lean_silicon_lsc1.sv`) and nothing else:

| Signal | Width | Direction at the ASIC | Meaning |
|---|---|---|---|
| `ui_in` | 8 | input | host-to-ASIC data byte |
| `uo_out` | 8 | output | ASIC-to-host data byte |
| `uio_in` | 8 | input | host-driven control bits |
| `uio_out` | 8 | output | ASIC-driven status bits |
| `uio_oe` | 8 | output | direction mask, `8'b10110110` |

Within `uio`, bits 0/3/6 are host-driven (`RX_VALID`, `TX_READY`, `ABORT`) and
bits 1/2/4/5/7 are ASIC-driven (`RX_READY`, `TX_VALID`, `BUSY`, `FAULT`,
`DONE_PULSE`).  The direction mask is the authority; the harness must tri-state
accordingly and must never back-drive an ASIC-driven bit.

Transfer rule, unchanged from `docs/LSC1_PROTOCOL.md`: a beat occurs only on a
rising clock edge where valid and ready are both high, and data plus valid stay
stable while stalled. The harness may not treat `BUSY`, `FAULT`, or `DONE_PULSE`
as a substitute for the handshake.

## Prohibited: wide internal compatibility bypasses

The failure mode this exists to prevent is a harness that, for convenience or
for speed, hands the ASIC a wide value directly and reports the result as if it
had come through the pins. All of the following are prohibited inside
`fpga_harness/`:

1. **Wide ASIC-facing ports.** No port crossing to the ASIC may exceed 8 bits.
   Checked: `boundary_check.py` fails on any harness port wider than 8 bits.
2. **Parallel operand injection.** No writing a 128-bit operand, `pc`, `fp`, or
   packet field into core state through anything other than accepted byte beats.
3. **Result extraction that skips `TX_VALID`/`TX_READY`.** Reading a result out
   of an internal register, a debug scan chain, or a simulation hierarchical
   reference is not an observation of the interface.
4. **Handshake shortcutting.** Tying `RX_VALID` or `TX_READY` permanently high,
   or ignoring `RX_READY`, defeats the contract even at the correct width.
5. **A second functional path of any width.** One interface, or it is not a
   pin-accurate harness.

Wide datapaths are permitted *strictly on the host side of the pins*: a harness
may assemble or buffer whole packets in wide registers or block RAM, provided
every byte still enters and leaves the ASIC through the 8-bit beats. Buffering
is allowed; bypassing is not.

One consequence, stated explicitly because the checker is stricter than the
prose above: `boundary_check.py` cannot tell an ASIC-facing port from a
host-side one, so it rejects *every* module port under `fpga_harness/rtl/`
wider than 8 bits. Wide host-side buffering must therefore live in internal
signals rather than module ports. This is a deliberate fail-safe: relaxing it
takes a reviewed change to this document and the checker together, not a port
that happens to be named as if it were host-side.

## What the harness must not own

The harness is a board/debug target. It is not a service provider, and adding
any of these would change what LSC-1 is:

- no autonomous instruction fetch and no program storage;
- no VM memory ownership;
- no SDRAM, PSRAM, or USB controller acting as an ASIC service;
- no pointer resolver, no field inverter, no BLAKE3 datapath;
- no deferred-equality state and no trace store.

The host retains all of the above. LSC-1 processes one host-prepared,
self-contained transaction at a time.

## Enforcement and its limits

`boundary_check.py` checks, from source, on every `make check`:

- the five interface ports are each declared `[7:0]` **and face the direction
  the contract requires** — `ui_in` and `uio_in` in, `uo_out`, `uio_out` and
  `uio_oe` out — so a reversed port cannot pass on width alone;
- `uio_oe` equals `8'b10110110`;
- `uio` roles agree between `info.yaml` and `docs/LSC1_PROTOCOL.md`;
- every term of the `uio_out` concatenation is exactly one bit. Eight
  comma-separated terms is not eight bits: a ranged select such as `bus[7:0]`,
  or a bare name that resolves to a wide net, would overflow the concatenation
  and silently shift every status pin below it;
- every `uio` bit the mask marks as an input is tied to zero in `uio_out`, and
  every bit marked as an output is driven by a real signal;
- no port exceeds 8 bits in any `.sv` or `.v` file found recursively under
  `fpga_harness/rtl/`. Width is counted across packed and unpacked dimensions
  together and includes the width implied by the data type, so `integer`,
  `[7:0][3:0]`, `[7:0] b [15:0]`, and a name sharing a declaration after a
  comma are all measured. A port whose width cannot be resolved — an
  unresolvable parameter, or a user-defined or package-scoped type — is
  rejected rather than assumed narrow;
- every module port is governed by a direction keyword. A directionless port,
  such as a SystemVerilog interface, carries no `input`/`output`/`inout` for
  the width scan to find, so it is reported rather than assumed narrow.
  Function and task arguments are excluded from this scan: they are internal,
  and wide internal datapaths are permitted.

What it does **not** do, stated plainly: it is a structural source check. It does
not prove sequential handshake conformance, it does not simulate, and it cannot
detect a bypass expressed through means it does not parse. It reduces the
plausible ways to break the rule; it does not close them. Behavioural
conformance needs a handshake testbench, and physical conformance needs
hardware — neither exists yet.

Role-name matching is deliberately tolerant: an unrecognised driver signal name
is reported as an observation rather than a failure, so that another lane
renaming an internal RTL signal cannot turn this check into a false alarm. The
objective violations above are hard failures.

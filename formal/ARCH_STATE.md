# LSC-1 registered architectural state

`lsc1_packet_frontend` exports `arch_*` as a passive, clock-boundary observation
interface. It has no input and cannot alter the packet endpoint. The complete
machine-readable field map is `lsc1_packet_frontend_arch_state_map.json`.

The state is partitioned exhaustively by `arch_phase` and the registered parser,
response, ALU, and encoder busy flags: reset, idle, parser, compute, response,
and retire. The partition names are review labels, not assumptions; the checker
asserts coverage mechanically.

## Source-grounded inventory and dependency graph

| State owner | Registered information exported | Future observable dependency |
| --- | --- | --- |
| RX parser | phase, header/body positions, declared length, header context, CRCs, complete accepted frame and parser fault | request acceptance and command dispatch |
| Frontend | compute phase, staged transaction/CRC, committed PC/FP, sequence, profile, status/fault | profile choice, RETIRE, STATUS, future request validation |
| TX serializer | active, byte index, saved status/length/payload, saved CRC, working envelope/payload CRCs, completion and payload CRC | `tx_valid`, every response byte, and the next checksum state under backpressure |
| ALU adapter and core | phase, saved opcode/operands, payload/result positions, result/fault/pulse, core phase/index/scratch, GF shift/accumulator | deferred arithmetic completion and next stream byte |
| Field encoder and nested multiplier | busy, start/progress, index, accumulator, operands, result/fault/pulse, and the nested adapter/core/GF state | pointer witness completion and every intermediate multiplication cycle |

```
RX registered frame ──► frontend decode/compute ──► staged result ──► TX registered serializer ──► tx_valid/tx_data
       │                         │                       │
       │                         ├──► ALU adapter ────────┤
       │                         └──► field encoder ──────┤
       └── parser position/CRC                         RETIRE ──► committed PC/FP, sequence
                                                        NEGOTIATE ──► active profile (capability 0x00000002)
```

All arrows cross registered boundaries except the listed busy/output functions.
The map has explicit bit widths. The checker requires every public `arch_*`
port, every nonblocking-assigned state element in the active recursive module
tree, and every packet output reconstruction to be covered. Its mutation guard
rejects altered TX CRC and saved-operand mappings.

`R(rtl, arch)` is direct equality to the mapped registered RTL signal. The only
derived fields are busy flags and protocol outputs, whose source registers are
listed in the RTL modules. Parser payload, framed opcode/length, TX payload and
serializer index are deliberately included: they can affect a later observable
response. Procedural decode temporaries (`txn_id`, offsets, decisions and local
write candidates) are excluded because they are not retained across a clock.

The one-cycle relation is the production clocked transition relation under the
same `(rst_n, abort, rx_data, rx_valid, tx_ready)` inputs. The bounded
`lsc1_packet_frontend_one_cycle_boundary` formal harness and its executable
SystemVerilog counterpart cover the whole integrated frontend boundary (not
just the parser): abort's next state clears queued work, starts no subunit,
drops the staged result, and records `0x93`; a quiescent frontend stutters every
retained transaction, commit, profile, and status field.
`tools/check_frontend_one_cycle_boundary.py` makes omissions and the two abort
next-state mutations fail mechanically. Reset still clears the map with profile
1. No cutpoints, black boxes, symbolic bridge state, or ignored output channel
is used.

## Concrete bounded accepted-path partitions

The former flat full-frontend SAT attempt is not treated as evidence: its
flattening of the large decode cone timed out.  The milestone runner instead
proves two concrete RTL partitions with `-verify`: a reset-established packet
receiver accepts the exact valid zero-length STATUS frame (including CRC), and
the shipped TX serializer emits its INFO envelope and CRC through two fixed
ready-low cycles.  The existing full-frontend executable test supplies the
connected non-vacuous SET path: accepted frame, decode, ALU completion,
response payload, and a 12-cycle output stall.

This is a bounded composed milestone, not a monolithic end-to-end formal proof:
the formal partitions do not prove that the controller connects every accepted
frame to every response, do not quantify over arbitrary/unbounded
backpressure, and do not establish release sequential equivalence.  Reset
coverage remains the separate receiver reset proof.  Release equivalence and
ASIC readiness remain explicit BLOCKS pending a reviewed phase-complete
architecture transition/refinement model.

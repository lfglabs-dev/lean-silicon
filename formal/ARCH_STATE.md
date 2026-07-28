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
same `(rst_n, abort, rx_data, rx_valid, tx_ready)` inputs. Reset clears the map
with profile 1; idle stutters when no input is accepted and no response is
active. At every cycle the public packet outputs agree with their architectural
observations. No cutpoints, black boxes, symbolic bridge state, or ignored
output channel is used.

This is a correspondence interface, not a claim of full LSC-1 refinement. The
next required proof is a phase-complete refinement from these fields to the
executable model; the smallest currently recorded failing partition must be
kept if that proof does not close.

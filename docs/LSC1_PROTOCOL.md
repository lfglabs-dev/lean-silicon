# LSC-1 packet protocol v1 (contract)

Transport is the Tiny Tapeout 8+8+8 interface: `ui_in` host-to-ASIC and
`uo_out` ASIC-to-host.  `uio[0]=RX_VALID`, `[1]=RX_READY`,
`[2]=TX_VALID`, `[3]=TX_READY`, `[4]=BUSY`, `[5]=FAULT`,
`[6]=ABORT`, `[7]=DONE`; directions are `8'b10110110`.
A beat occurs only when valid and ready are both high; data/valid remain stable
while stalled.  Version v1 uses little-endian u32 and F128.

A request is `SOF=0xa1, version=1, opcode, flags, length:u16, payload,
crc32`; it is self-contained and has exactly one response.  A response is
`SOF=0x5a, version=1, status, length:u16, payload, crc32`.  Malformed length,
CRC, opcode, witness, address overflow, or write-once conflict yields a fault
response and no partial scalar transition.

Request opcodes are XOR, MUL_NATIVE, SET_CONSTANT, DEREF_CELL, DEREF_PC,
DEREF_FP, JUMP, and BLAKE3_REQUEST.  Each request carries current `pc:u32`,
`fp:u32`, decoded operands/values, written bits, and any host witness needed
to validate the transition.  Responses carry `next_pc:u32`, `next_fp:u32`,
zero or more write-once updates, deferred-equality events, optional BLAKE3
service request, and retirement/fault.  Exact payload schemas, status and fault
codes, the transaction state machine, profile negotiation, the trust boundary,
and byte/cycle budgets are specified normatively in
[LSC1_TRANSACTION_PROTOCOL](LSC1_TRANSACTION_PROTOCOL.md), with the executable
model in `sim/lsc1_transaction.py`.  Neither document pretends to be RTL.

The present RTL top is protocol **seed-0**, not v1: it accepts the historical
fixed stream commands solely to keep MinCore arithmetic executable.  It must
not be used as a v1 packet endpoint.

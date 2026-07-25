# MinCore UART host diagnostic contract

This is a versioned diagnostic transport for the historical MinCore byte lane,
not LSC-1 packet execution.  The host CLI is `fpga_harness/host/mincore_uart.py`.

## Byte API supplied to the bridge writer

The host currently supports one transparent, ordered UART byte stream at an
agreed baud rate.  The host default is 115200 baud, configurable with `--baud`;
this is a host setting, not a claim about FPGA RTL.  In this raw diagnostic
mode, the bridge must preserve each MinCore byte and must not add in-band
flow-control bytes, retries, or commands.

| Operation | Host-to-bridge bytes | Bridge-to-host bytes |
|---|---|---|
| SET128 | `03 V0..V15` | `V0..V15` |
| XOR128 | `01 A0 B0 ... A15 B15` | `A0^B0 .. A15^B15` |
| MUL128 | `02 A0..A15 B0..B15` | 16 product bytes |
| CLEAR | `7d` | none |
| STATUS | `7e` | `01 01 0f 08` |

All F128 bytes are little-endian.  The definitive source locators are
`asic_core/rtl/leanvm_b_stream_alu.sv:8-24` (byte order, grammar and field),
`:46-51` (command values), `:105-115` (STATUS), `:132-148` (combinational
XOR/SET), and `docs/PROTOCOL_BYTE_CYCLE_AUDIT.md:41-78` (no framing, partial
transaction, and recovery limits).

## Required bridge decisions / ambiguity

There is no UART protocol in the MinCore RTL.  It accepts ready/valid bytes,
whereas UART is asynchronous; the bridge writer must provide buffering so it
does not drop UART bytes while `RX_READY=0`.  In particular XOR and SET have a
combinational input/output handshake (`leanvm_b_stream_alu.sv:136-147`).

`docs/PROTOCOL_BYTE_CYCLE_AUDIT.md:75-78` requires a production bridge to add
an envelope, integrity, timeout, and resynchronization policy.  That envelope
is not specified in this revision and therefore cannot be silently added to
this raw host tool: doing so needs a versioned host/bridge contract update.

`ABORT` is a separate synchronous pin, not a byte command
(`leanvm_b_stream_alu.sv:31` and `:220-225`).  A raw serial host cannot assert
it.  The CLI therefore never invents an abort byte and reports that limitation;
the bridge needs a separately specified abort control if recovery is required.
`CLEAR` only clears sticky fault and emits no response (`:238-241`), while an
unknown command emits `e0` and sets fault (`:242-245`, `:189-192`).  STATUS is
constant and does not expose fault.  Thus a bridge that needs a reliable host
fault indication must specify out-of-band status rather than overload raw data.

The host drains bytes already buffered before each transaction, reads exactly
the documented response length, rejects immediately buffered extras, times out
with byte progress, and does not retry.  After framing loss or timeout the
outcome is unknown; a raw UART-only bridge cannot safely resynchronize a
partial MinCore command.

## Usage

Encoding and dry-run modes never access hardware:

```sh
python3 fpga_harness/host/mincore_uart.py --operation mul --vector mul128 --encode
python3 fpga_harness/host/mincore_uart.py --operation set --vector set128 --dry-run --evidence evidence.jsonl
```

Serial execution requires both an explicit port and `--execute`; `pyserial`
is optional and only needed then.  This only demonstrates a host exchange with
the selected serial endpoint: it is not physical FPGA validation and does not
identify what is attached to that endpoint.

Evidence is JSONL and deliberately omits the port name.  Raw request, response,
and expected payloads are also omitted by default; lengths and SHA-256 digests
are recorded instead.  `--evidence-payloads` opts into recording those
potentially sensitive bytes.  Dry-run and encode records have
`execution_attempted: false`, an empty response, and `pass: null`; they never
substitute a golden expected value for an observed response.

# Silicon Live

Silicon Live is an evidence-first Textual dashboard for the 12-step physical
ULX3S LSC-1 run committed in this repository. The default demo is offline,
deterministic, opens no serial port, and ends at **PREFIX MATCH ✓**. This is
deliberately not called PASS: hardware stopped before the unsupported `Jump`.

## Install and run

From the repository root:

```console
python3 -m venv .venv
.venv/bin/pip install -r silicon_live/requirements.txt
.venv/bin/python -m silicon_live --demo
```

Or, when `uv` is available:

```console
uv run --with-requirements silicon_live/requirements.txt python3 -m silicon_live --demo
```

The dashboard starts replay immediately and needs no board. Run with an
explicit compatible artifact using `--evidence PATH`.

## What is on screen

The dashboard keeps zkDSL source, PC-local disassembly, exact 128-bit VM
memory, cell reads/writes, the current HOST → FPGA → HOST exchange, and a
structured event stream visible together. HOST is warm amber; FPGA is teal.
Green is reserved for validated writes and the prefix-match terminal. The
source highlight is explicitly marked `≈ approximate`, because the committed
compiler artifact has no exact source spans.

Representative real Textual captures:

- [Initial shell](docs/screenshots/01-initial-shell.svg)
- [Active middle step](docs/screenshots/02-active-middle-step.svg)
- [Narrow terminal](docs/screenshots/03-narrow-terminal.svg)
- [Final prefix match](docs/screenshots/04-prefix-match.svg)

## Controls

| Key | Action |
|---|---|
| `Space` | Run / pause |
| `S` | Execute one evidence step |
| `R` | Restart |
| `+` / `-` | Replay speed |
| `/` | Search events |
| `I` | Inspect exact current transaction and destination cell |
| `Tab` | Move panel focus |
| `?` | Keyboard help |
| `Ctrl+P` | Textual command palette |
| `Q` | Quit |

Memory cells always retain and render all 32 hexadecimal digits. Narrow
terminals switch to a vertically scrollable single-column layout.

## Architecture

- `model.py`: artifact loader, exact-u128 state, deterministic replay, and
  UI-independent prepare/send/compute/response/validate/write/halt/error events.
- `transport.py`: fake serial plus a lazy live adapter over the existing PR #16
  `MinCoreSerialDriver`. It never enumerates, opens, or loads hardware.
- `app.py`: presentation and commands only.
- `tests/`: loaders, events, memory, semantics, errors, fake serial, commands,
  progression, and responsive pilot coverage.

The evidence adapter is production-ready for the committed run. The live
adapter intentionally requires callers to provide an already-open serial
object; Silicon Live itself does not expose a hardware mode yet. HostRuntime
integration remains a presentation-compatible future adapter: its output
should be translated into the same event vocabulary.

## Visual QA

See [Visual QA log](docs/VISUAL_QA.md). Regenerate the four artifacts with:

```console
.venv/bin/python -m silicon_live.tests.capture_screenshots
```

## Limitations

- Source-to-instruction highlighting is approximate; the artifact contains no
  exact span table.
- Evidence ends at PC 12 because `Jump` is unsupported by the seed-0 UART
  runner. The correct conclusion is prefix match, never full-program pass.
- Search currently filters structured event messages; visible memory and
  instruction text remain directly inspectable but do not yet jump to a row.
- Live serial use is adapter-only and intentionally never automatic.

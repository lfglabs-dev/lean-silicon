# Visual QA log

All captures below were produced by separate real Textual `run_test` pilot
launches and `App.save_screenshot`; none are mockups. PNGs are rendered from
those exact SVG captures. This log records the defects found during three
capture/revise passes, not merely artifact existence.

1. **Initial shell** — `docs/screenshots/01-initial-shell.svg`
   Checked hierarchy and idle-state density. Kept the persistent status strip,
   quiet muted metadata, and empty transaction state so the first frame
   communicates program/backend/connection before animation.
2. **Active middle step** — `docs/screenshots/02-active-middle-step.svg`
   Pass 1 exposed near-monochrome actors, concatenated `HOSTprepare` rows,
   orphaned UART hex, and an event stream wider than the focal transaction.
   Pass 2 added high-contrast HOST/FPGA pills, fixed label columns, bounded
   prefix/suffix wire previews with exact data available via `I`, and reduced
   the event panel. Pass 3 strengthened the violet current-PC selection and
   PC→FPGA→PC card border. READ is amber and WRITE is green.
3. **Narrow terminal** — `docs/screenshots/03-narrow-terminal.svg`
   Pass 1 clipped the command strip (`Sear…`) and produced awkward panel
   overflow. Pass 2 hid the redundant Textual footer below 92 columns, added a
   compact command line, and tightened panel heights. Pass 3 verified deliberate
   source/disassembly → transaction/memory → recent-events order, spaced status
   rows, and stable abbreviated UART previews at 76×48.
4. **Final prefix match** — `docs/screenshots/04-prefix-match.svg`
   Pass 1 left the outcome as a low-salience footer sentence. Pass 2 promoted it
   to a bordered green result card. Pass 3 verified the explicit
   `evidence replay · no board` qualifier and amber unsupported-Jump limitation
   remain visible. The exact result is `PREFIX MATCH ✓`; no PASS label appears.

Palette: `#101217` background, `#181b22` surfaces, `#eee9df` primary text,
`#9aa3b2` metadata, `#f2ae72` HOST, `#64d2c8` FPGA, `#80d98b` success/write,
`#f0c36a` read/warning, `#f07b7b` faults, and `#d5a6e6` PC/focus. Semantic color
is deliberately limited to avoid rainbow noise.

# Visual QA log

All captures below were produced by separate real Textual `run_test` pilot
launches and `App.save_screenshot`; none are mockups.

1. **Initial shell** — `docs/screenshots/01-initial-shell.svg`
   Checked hierarchy and idle-state density. Kept the persistent status strip,
   quiet muted metadata, and empty transaction state so the first frame
   communicates program/backend/connection before animation.
2. **Active middle step** — `docs/screenshots/02-active-middle-step.svg`
   Checked PC context, HOST/FPGA separation, u128 alignment, and read/write
   salience. Reads use warning amber; the sole write uses success green; the
   current instruction uses one restrained violet selection. The first render
   pushed low-order memory digits into horizontal overflow; compact `Rm02` /
   `Wm06` row markers now keep all 32 hex digits visible.
3. **Narrow terminal** — `docs/screenshots/03-narrow-terminal.svg`
   Checked clipping and overflow at 76×48. The workspace becomes one vertically
   scrollable column, panels receive explicit heights, and no panel retains the
   wide-layout minimum width. A second render exposed the wide status strip and
   wire bytes overflowing; narrow status is now two lines and TX/RX bytes wrap
   at deterministic boundaries.
4. **Final prefix match** — `docs/screenshots/04-prefix-match.svg`
   Checked terminal wording and contrast. The result is the exact
   `PREFIX MATCH ✓`, with the unsupported-Jump reason adjacent; no PASS label is
   rendered.

Palette: `#111318` background, `#191c23` surfaces, `#e8e3d8` primary text,
`#8f96a3` metadata, `#d9a36c` HOST, `#70b8b0` FPGA, `#82b883` success/write,
`#d3ad62` read/warning, `#d87575` faults, and `#c89ad1` PC/focus. Semantic color
is deliberately limited to avoid rainbow noise.

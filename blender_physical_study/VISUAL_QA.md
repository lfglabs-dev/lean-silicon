# Visual QA log

This log is updated only after opening the real rendered pixels. Checks cover
clipping, overlaps, color hierarchy, exposure, framing, and permanent notice
readability.

| Iteration | Artifact | Inspection and action |
|---|---|---|
| 1 | `preview_hero.png` | Real 640×360 preview was too dark; type/layer hierarchy was obscured and the notice was outside frame. Raised AgX exposure and three-point energies, kept Geometry Nodes prototypes render-resolvable, and moved the notice inward. |
| 2 | `preview_hero.png` | Exposure and colored-layer separation were acceptable. Camera-locked notice was still absent because parent-space placement was unreliable. Replaced parenting with an explicit camera-to-world matrix. |
| 3 | `preview_hero.png` | Notice became visible but mirrored due to a 180° font rotation. Removed the rotation before final rendering. |
| 4 | `contact_sheet.jpg` | Inspected real hero, exploded, top, and close-up renders together. No clipping of the die in hero/top; close-up intentionally crops the die. Layer overlaps are legible as an abstract stack, exposure retains dark substrate detail, cyan/orange/purple hierarchy is visible, and the permanent notice is high-contrast/readable in every frame. Exploded spacing is visible but intentionally restrained to preserve die context. |
| 5 | `hero_transparent.png` | Verified 3840×2160 RGBA output; camera-locked opaque notice remains readable against transparency. |

The preview took 26.21 seconds at one Eevee sample. A 240-frame,
10-second/24fps orbit therefore projects to about 104.8 minutes before encode
on this host. It was judged outside the bounded rendering window; the optional
reproduction command remains available with `--animation`.

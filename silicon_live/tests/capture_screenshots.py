"""Generate deterministic, committed visual-QA artifacts with real Textual pilots."""
from __future__ import annotations
import asyncio
import os
from pathlib import Path
import subprocess

os.environ.pop("NO_COLOR", None)
os.environ["TERM"] = "xterm-256color"
os.environ["COLORTERM"] = "truecolor"

from silicon_live.app import SiliconLive

OUT = Path(__file__).resolve().parents[1] / "docs/screenshots"


async def capture(name: str, size: tuple[int, int], steps: int) -> None:
    app = SiliconLive(auto_run=False)
    async with app.run_test(size=size) as pilot:
        for _ in range(steps):
            app.action_step()
        await pilot.pause()
        svg = Path(app.save_screenshot(filename=f"{name}.svg", path=str(OUT)))
        subprocess.run(
            ["rsvg-convert", str(svg), "-o", str(svg.with_suffix(".png"))],
            check=True,
        )


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # Separate app/pilot launches ensure mount, layout, and rendering are all real.
    await capture("01-initial-shell", (140, 42), 0)
    await capture("02-active-middle-step", (140, 42), 6)
    await capture("03-narrow-terminal", (76, 48), 7)
    await capture("04-prefix-match", (140, 42), 12)


if __name__ == "__main__":
    asyncio.run(main())

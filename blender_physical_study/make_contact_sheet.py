#!/usr/bin/env python3
"""Create the committed visual-QA contact sheet from real renders."""

from pathlib import Path
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
OUT = HERE / "artifacts"
FILES = ["hero_4k.png", "exploded_stack.png", "top_view.png", "close_up.png"]

canvas = Image.new("RGB", (1920, 1080), "#060b14")
draw = ImageDraw.Draw(canvas)
for index, name in enumerate(FILES):
    image = Image.open(OUT / name).convert("RGB")
    image.thumbnail((920, 460))
    x = 40 + (index % 2) * 960
    y = 35 + (index // 2) * 530
    canvas.paste(image, (x + (920 - image.width) // 2, y + 25))
    draw.text((x, y + 495), name, fill="#e6f2ff")
canvas.save(OUT / "contact_sheet.jpg", quality=90, optimize=True)

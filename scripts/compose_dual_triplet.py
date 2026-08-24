#!/usr/bin/env python3
"""Compose three synchronized source/local browser captures into one QA sheet."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT_CANDIDATES = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--step", required=True)
    parser.add_argument("--title", required=True)
    args = parser.parse_args()

    frame_labels = ("0.0s", "0.5s", "1.0s")
    source_paths = [args.base / "raw" / "source" / f"{args.step}-{index}.png" for index in range(3)]
    local_paths = [args.base / "raw" / "local" / f"{args.step}-{index}.png" for index in range(3)]

    sources = [Image.open(path).convert("RGB") for path in source_paths]
    locals_ = [Image.open(path).convert("RGB") for path in local_paths]
    viewport_width, viewport_height = sources[0].size
    if any(image.size != (viewport_width, viewport_height) for image in sources + locals_):
        raise ValueError("All screenshots must have the same viewport dimensions")

    title_height = 64
    label_height = 44
    row_height = label_height + viewport_height
    sheet = Image.new("RGB", (viewport_width * 2, title_height + row_height * 3), "#111827")
    draw = ImageDraw.Draw(sheet)
    title_font = load_font(28)
    label_font = load_font(22)

    draw.text((24, 16), args.title, fill="#ffffff", font=title_font)
    for index, label in enumerate(frame_labels):
        y = title_height + index * row_height
        draw.rectangle((0, y, viewport_width, y + label_height), fill="#fff7ed")
        draw.rectangle((viewport_width, y, viewport_width * 2, y + label_height), fill="#eff6ff")
        draw.text((20, y + 8), f"妙笔神书 · {label}", fill="#c2410c", font=label_font)
        draw.text((viewport_width + 20, y + 8), f"本项目 · {label}", fill="#1d4ed8", font=label_font)
        sheet.paste(sources[index], (0, y + label_height))
        sheet.paste(locals_[index], (viewport_width, y + label_height))

    output = args.base / "compare" / f"{args.step}-triplet.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, optimize=True)
    print(output)


if __name__ == "__main__":
    main()

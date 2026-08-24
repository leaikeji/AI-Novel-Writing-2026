"""Compose synchronized source/local audit screenshots into side-by-side PNGs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import csv
from pathlib import Path
import re
import sys

from PIL import Image, ImageDraw, ImageFont


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def compose(source_path: Path, local_dir: Path, output_dir: Path) -> str:
    local_path = local_dir / source_path.name
    if not local_path.exists():
        return f"missing:{source_path.name}"
    output_path = output_dir / source_path.name
    if output_path.exists():
        return "skipped"

    with Image.open(source_path) as source_image, Image.open(local_path) as local_image:
        source = source_image.convert("RGB")
        local = local_image.convert("RGB")
        header_height = 56
        body_height = max(source.height, local.height)
        canvas = Image.new(
            "RGB",
            (source.width + local.width, header_height + body_height),
            "white",
        )
        canvas.paste(source, (0, header_height))
        canvas.paste(local, (source.width, header_height))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, source.width, header_height), fill="#202124")
        draw.rectangle(
            (source.width, 0, source.width + local.width, header_height),
            fill="#fff7f1",
        )
        draw.line(
            (source.width, 0, source.width, header_height + body_height),
            fill="#ff7548",
            width=4,
        )
        font = load_font(25)
        draw.text((24, 12), "妙笔神书", fill="white", font=font)
        draw.text((source.width + 24, 12), "本项目", fill="#8b3e22", font=font)
        canvas.save(output_path, format="PNG", compress_level=6)
    return "written"


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: compose_audit_pairs.py EVIDENCE_DIR")
    base = Path(sys.argv[1]).resolve()
    source_dir = base / "raw" / "source"
    local_dir = base / "raw" / "local"
    output_dir = base / "compare" / "all-pairs"
    output_dir.mkdir(parents=True, exist_ok=True)
    source_paths = sorted(source_dir.glob("*.png"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda path: compose(path, local_dir, output_dir),
                source_paths,
            )
        )
    written = results.count("written")
    skipped = results.count("skipped")
    missing = sum(result.startswith("missing:") for result in results)
    grouped: dict[str, dict[int, str]] = {}
    for path in sorted(output_dir.glob("*.png")):
        match = re.fullmatch(r"(.+)-([012])\.png", path.name)
        if match:
            grouped.setdefault(match.group(1), {})[int(match.group(2))] = path.name
        else:
            grouped.setdefault(path.stem, {})[0] = path.name
    manifest_path = base / "compare" / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as manifest_file:
        writer = csv.writer(manifest_file, lineterminator="\n")
        writer.writerow(("operation_group", "immediate", "plus_0_5s", "plus_1_0s"))
        for group, captures in sorted(grouped.items()):
            writer.writerow(
                (
                    group,
                    captures.get(0, ""),
                    captures.get(1, ""),
                    captures.get(2, ""),
                )
            )
    print(
        f"paired={len(source_paths)} written={written} "
        f"skipped={skipped} missing={missing} groups={len(grouped)} "
        f"output={output_dir} manifest={manifest_path}"
    )
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())

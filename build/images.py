"""Train images: data/trains/ + data/train_images.csv → v0/trains/*.webp with thumbnails.

The CSV says which series each file shows and whether it is AI-generated, so apps can label it.
A row with no `line` is the model's default picture. A row with `line` (one or more line ids)
shows the livery those lines use, and is given on those lines only: the E233 in Chūō Rapid
orange should not illustrate a Keihin-Tōhoku ride.
"""

import csv
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "trains"
OUT = ROOT / "v0" / "trains"
FULL_W = 1200
THUMB_W = 400
QUALITY = 82


def resized(image, width):
    if image.width <= width:
        return image
    return image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)


def build(series_ids, line_ids, report):
    """Write the WebP files.

    Return ({series: default image}, {(series, line): line image}); paths are relative to v0/.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    defaults, by_line, written = {}, {}, set()
    with open(ROOT / "data" / "train_images.csv", encoding="utf-8") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            where = f"data/train_images.csv line {n}"
            series = row["series"]
            lines = (row.get("line") or "").split()
            if series not in series_ids:
                raise SystemExit(f"{where}: unknown series {series!r}")
            for line in lines:
                if line not in line_ids:
                    raise SystemExit(f"{where}: unknown line {line!r}")
                if (series, line) in by_line:
                    raise SystemExit(f"{where}: {series} already has an image for {line}")
            if not lines and series in defaults:
                raise SystemExit(f"{where}: {series} already has a default image")
            source = SOURCE / row["file"]
            if not source.exists():
                raise SystemExit(f"{where}: data/trains/{row['file']} is missing")

            name = f"{series}--{lines[0]}" if lines else series
            image = Image.open(source).convert("RGB")
            full, thumb = resized(image, FULL_W), resized(image, THUMB_W)
            full.save(OUT / f"{name}.webp", "WEBP", quality=QUALITY, method=6)
            thumb.save(OUT / f"{name}-thumb.webp", "WEBP", quality=QUALITY, method=6)
            written |= {f"{name}.webp", f"{name}-thumb.webp"}
            record = {
                "url": f"trains/{name}.webp",
                "thumb": f"trains/{name}-thumb.webp",
                "width": full.width,
                "height": full.height,
                "generated": row["generated"].strip().lower() in ("yes", "true", "1"),
                "credit": row["credit"] or None,
                "licence": row["licence"] or None,
                "note": row["note"] or None,
            }
            if lines:
                for line in lines:
                    by_line[(series, line)] = record
            else:
                defaults[series] = record

    for stale in OUT.glob("*.webp"):
        if stale.name not in written:
            stale.unlink()
    pictured = set(defaults) | {s for s, _ in by_line}
    if len(pictured) < len(series_ids):
        report.append(f"{len(series_ids) - len(pictured)} of {len(series_ids)} series have no image")
    return defaults, by_line

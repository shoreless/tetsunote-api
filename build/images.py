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
PHOTO_W = 960
PHOTO_QUALITY = 72


def resized(image, width):
    if image.width <= width:
        return image
    return image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)


def listed():
    """Series ids that have a picture of their own in data/train_images.csv."""
    with open(ROOT / "data" / "train_images.csv", encoding="utf-8") as f:
        return {row["series"] for row in csv.DictReader(f)}


def build(series_ids, line_ids, report, fallbacks=()):
    """Write the WebP files.

    `fallbacks` are extra default pictures (Commons photos) for series without one of their own.
    Return ({series: default image}, {(series, line): line image}); paths are relative to v0/.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    defaults, by_line, written = {}, {}, set()

    def write(series, lines, source, row):
        name = f"{series}--{lines[0]}" if lines else series
        image = Image.open(source).convert("RGB")
        # Photos carry more detail than the flat illustrations and weigh twice as much: keep them smaller.
        width, quality = (FULL_W, QUALITY) if row is not None and "path" not in row else (PHOTO_W, PHOTO_QUALITY)
        full, thumb = resized(image, width), resized(image, THUMB_W)
        full.save(OUT / f"{name}.webp", "WEBP", quality=quality, method=6)
        thumb.save(OUT / f"{name}-thumb.webp", "WEBP", quality=quality, method=6)
        written.update({f"{name}.webp", f"{name}-thumb.webp"})
        return {
            "url": f"trains/{name}.webp",
            "thumb": f"trains/{name}-thumb.webp",
            "width": full.width,
            "height": full.height,
            "generated": row["generated"],
            "credit": row.get("credit") or None,
            "licence": row.get("licence") or None,
            "licence_url": row.get("licence_url") or None,
            "source_url": row.get("source_url") or None,
            "note": row.get("note") or None,
        }

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
            row = dict(row, generated=row["generated"].strip().lower() in ("yes", "true", "1"))
            record = write(series, lines, source, row)
            if lines:
                for line in lines:
                    by_line[(series, line)] = record
            else:
                defaults[series] = record

    pictured = set(defaults) | {s for s, _ in by_line}
    for row in fallbacks:
        if row["series"] not in pictured:
            defaults[row["series"]] = write(row["series"], [], row["path"], row)
            pictured.add(row["series"])

    for stale in OUT.glob("*.webp"):
        if stale.name not in written:
            stale.unlink()
    if len(pictured) < len(series_ids):
        report.append(f"{len(series_ids) - len(pictured)} of {len(series_ids)} series have no image")
    return defaults, by_line

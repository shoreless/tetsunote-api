"""Mascots and characters (data/mascots.csv: v0/mascots.json) and legends (data/lore.csv: v0/lore.json).

Background for the line and train pages, not a collection: an operator's mascot (とぶっち, そうにゃん),
a line's (カンセンジャー), station idols and characters (STATION IDOL LATCH! on the 山手線, やなせたかし's
characters on ごめん・なはり線), animal stationmasters (たま at 貴志), and Shinkalion robots and
Zairiners, each on the train it's based on.

Rows name an `operator`, and optionally `lines` (ids after the operator's dot), `stations` (Japanese
names, found on the operator's lines) and `series` (train model ids). A row with an operator and no
lines or stations belongs to every line of the operator; one with stations belongs to the lines those
stations are on. Facts come from Japanese Wikipedia's lists (facts only; notes are our own words) and
Wikidata; `{station}` in a note becomes the station's name. Only real animals get a photo: a drawn
character's art is its owner's, and Wikidata's pictures for mascots are often of a train or station.
"""

import csv
from pathlib import Path

from facts import wiki_url

ROOT = Path(__file__).resolve().parent.parent
def same(a, b):
    """Station names as written differently: ヶ, ケ and ヵ are the same small ke."""
    fold = str.maketrans("ケヵ", "ヶヶ")
    return a.translate(fold) == b.translate(fold)


KINDS = {"mascot", "idol", "station-character", "animal", "shinkalion"}
STATUS = {"active", "retired", "in-memoriam"}


class Resolver:
    """Finds the lines, stations and trains a row of mascots.csv or lore.csv belongs to."""

    def __init__(self, shards, series_ids, report):
        self.lines = {line["id"]: (shard, line) for shard in shards.values() for line in shard["lines"]}
        self.by_operator = {}
        for line_id in self.lines:
            self.by_operator.setdefault(line_id.split(".")[0], []).append(line_id)
        self.series_ids = series_ids
        self.report = report

    def stations_on(self, line_id):
        shard, line = self.lines[line_id]
        ids = {x for seg in line["segments"] for x in (seg["from"], seg["to"])}
        return [shard["stations"][s] for s in ids if s in shard["stations"]]

    def resolve(self, row, where, label):
        """(line ids, station records, series ids), or None when the row belongs nowhere we know."""
        op = row["operator"]
        if op and op not in self.by_operator:
            raise SystemExit(f"{where}: unknown operator {op!r}")
        named = [f"{op}.{x}" for x in row["lines"].split()]
        for line_id in named:
            if line_id not in self.lines:
                raise SystemExit(f"{where}: unknown line {line_id!r}")
        series = row["series"].split()
        for s in series:
            if s not in self.series_ids:
                raise SystemExit(f"{where}: unknown train model {s!r}")
        # Stations: on the named lines first, else anywhere on the operator's lines.
        stations, on_lines = [], []
        for name in row["stations"].split():
            found = None
            for line_id in named + [l for l in self.by_operator.get(op, []) if l not in named]:
                match = next((s for s in self.stations_on(line_id) if same(s["name"]["ja"], name)), None)
                if match:
                    found, on = match, line_id
                    break
            if not found:
                self.report.append(f"{label}: {where}: no station {name} on {op}")
                continue
            stations.append(found)
            on_lines.append(on)
        if row["stations"] and not stations:
            return None
        line_ids = named or sorted(set(on_lines)) or ([] if series else sorted(self.by_operator.get(op, [])))
        if not line_ids and not series:
            self.report.append(f"{label}: {where}: on no line or train")
            return None
        return line_ids, stations, series


def with_station(text, stations, lang):
    if not text:
        return None
    if stations:
        text = text.replace("{station}", stations[0]["name"].get(lang) or stations[0]["name"]["ja"])
    return text


def build(resolver):
    records = []
    for n, row in enumerate(csv.DictReader((ROOT / "data" / "mascots.csv").open(encoding="utf-8")), start=2):
        where = f"data/mascots.csv line {n} ({row['id']})"
        if row["kind"] not in KINDS:
            raise SystemExit(f"{where}: unknown kind {row['kind']!r}")
        if row["status"] not in STATUS:
            raise SystemExit(f"{where}: unknown status {row['status']!r}")
        found = resolver.resolve(row, where, "mascots")
        if not found:
            continue
        line_ids, stations, series = found
        records.append({
            "id": row["id"],
            "kind": row["kind"],
            "name": {"ja": row["ja"], "en": row["en"] or None, "reading": row["reading"] or None},
            "operator": row["operator"] or None,
            "lines": line_ids,
            "stations": [s["id"] for s in stations],
            "series": series,
            "status": row["status"],
            "since": row["since"] or None,
            "until": row["until"] or None,
            "species": row["species"] or None,
            "unit": row["unit"] or None,
            "note": {"en": with_station(row["note_en"], stations, "en"), "ja": with_station(row["note_ja"], stations, "ja")},
            "wikidata": row["wikidata"] or None,
            "links": {
                "official": row["official"] or None,
                "wikipedia_ja": wiki_url("ja", row["wikipedia_ja"]) if row["wikipedia_ja"] else None,
                "wikidata": f"https://www.wikidata.org/wiki/{row['wikidata']}" if row["wikidata"] else None,
            },
        })
    return records


LORE_KINDS = {"lucky-train", "charm", "name-origin", "lucky-station"}


def build_lore(resolver):
    """Legends and lucky things of lines, trains and stations, from data/lore.csv: v0/lore.json."""
    records = []
    for n, row in enumerate(csv.DictReader((ROOT / "data" / "lore.csv").open(encoding="utf-8")), start=2):
        where = f"data/lore.csv line {n} ({row['id']})"
        if row["kind"] not in LORE_KINDS:
            raise SystemExit(f"{where}: unknown kind {row['kind']!r}")
        if row["status"] not in {"active", "past"}:
            raise SystemExit(f"{where}: status is active or past, not {row['status']!r}")
        found = resolver.resolve(row, where, "lore")
        if not found:
            continue
        line_ids, stations, series = found
        records.append({
            "id": row["id"],
            "kind": row["kind"],
            "title": {"ja": row["ja"], "en": row["en"] or None},
            "lines": line_ids,
            "stations": [s["id"] for s in stations],
            "series": series,
            "status": row["status"],
            "note": {"en": with_station(row["note_en"], stations, "en"), "ja": with_station(row["note_ja"], stations, "ja")},
            "links": {"wikipedia_ja": wiki_url("ja", row["wikipedia_ja"]) if row["wikipedia_ja"] else None},
        })
    return records

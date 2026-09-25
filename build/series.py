"""Train models (series) and the lines they run on, from data/series.csv and data/line_series.csv.

Neither is in N02, and Wikidata rarely says which line a model runs on, so both lists are curated.
Wikidata supplies only each model's id, matched by English name from the operators' fleets.
"""

import csv
import re
import urllib.parse
import urllib.request
from pathlib import Path

from names import USER_AGENT, ascii_name

ROOT = Path(__file__).resolve().parent.parent
FLEET = ROOT / "sources" / "wikidata" / "fleet.csv"
FLEET_QUERY = """
SELECT ?series ?ja ?en WHERE {
  ?series wdt:P137 ?operator ; wdt:P176 ?maker .
  ?operator wdt:P17 wd:Q17 .
  OPTIONAL { ?series rdfs:label ?ja FILTER(lang(?ja)="ja") }
  OPTIONAL { ?series rdfs:label ?en FILTER(lang(?en)="en") }
}
"""
KINDS = {"commuter", "limited-express", "shinkansen", "diesel", "tram", "monorail", "agt", "cable"}
STATUSES = {"active", "retiring", "retired"}


def key(name):
    return re.sub(r"[^a-z0-9]", "", (ascii_name(name) or "").lower())


def wikidata_ids():
    if not FLEET.exists():
        print("Querying Wikidata for train models")
        url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": FLEET_QUERY})
        request = urllib.request.Request(url, headers={"Accept": "text/csv", "User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=300) as response:
            body = response.read()
        if not body.startswith(b"series,"):
            raise SystemExit("Wikidata returned no train models; try again later")
        FLEET.write_bytes(body)
    found = {}
    with open(FLEET, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("en"):
                found.setdefault(key(row["en"]), row["series"].rsplit("/", 1)[-1])
    return found


def load(line_ids, report):
    """Return (series records for v0/series.json, {line id: [{"id", "status"}]})."""
    qids = wikidata_ids()
    series = {}
    with open(ROOT / "data" / "series.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["id"] in series:
                raise SystemExit(f"data/series.csv: {row['id']} is listed twice")
            if row["kind"] not in KINDS or row["status"] not in STATUSES:
                raise SystemExit(f"data/series.csv: {row['id']} has kind {row['kind']!r}, status {row['status']!r}")
            series[row["id"]] = {
                "id": row["id"],
                "name": {"en": row["en"], "ja": row["ja"]},
                "operators": row["operator"].split(),
                "kind": row["kind"],
                "status": row["status"],
                "wikidata": qids.get(key(row["en"])),
                "checked": row["checked"] or None,
                "source": row["source"] or None,
            }

    by_line = {}
    with open(ROOT / "data" / "line_series.csv", encoding="utf-8") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            where = f"data/line_series.csv line {n}"
            if row["series"] not in series:
                raise SystemExit(f"{where}: unknown series {row['series']!r}")
            if row["status"] not in STATUSES:
                raise SystemExit(f"{where}: status {row['status']!r}")
            if row["line"] not in line_ids:
                report.append(f"{where}: unknown line {row['line']!r}")
                continue
            by_line.setdefault(row["line"], []).append({"id": row["series"], "status": row["status"]})

    order = {"active": 0, "retiring": 1, "retired": 2}
    for items in by_line.values():
        items.sort(key=lambda s: order[s["status"]])
    return [series[k] for k in sorted(series)], by_line

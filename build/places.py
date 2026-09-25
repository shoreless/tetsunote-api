"""Places for railway fans: museums, maglev and heritage railways from Wikidata, plus data/places.csv.

Wikidata (CC0) supplies railway museums, transport museums with a railway name, and heritage railways
in Japan, skipping any it records as closed. data/places.csv adds places Wikidata lacks (a train bar,
a photo spot) and hides or corrects ones it has. Each place gets its nearest stations from our data.
Query results are cached in sources/wikidata/places.csv; delete it to refresh.
"""

import csv
import math
import re
import urllib.parse
import urllib.request
from pathlib import Path

from names import USER_AGENT, ascii_name

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "sources" / "wikidata" / "places.csv"
CURATED = ROOT / "data" / "places.csv"
KINDS = {
    "museum", "maglev", "heritage-railway", "railway-park", "historic-station",
    "bar", "cafe", "shop", "viewpoint", "other",
}
NEAR_M = 3000

QUERY = """
SELECT ?p ?cls ?ja ?en ?coord ?site ?closed WHERE {
  VALUES ?cls { wd:Q18704634 wd:Q2516357 wd:Q420962 }
  ?p wdt:P31 ?cls; wdt:P17 wd:Q17; wdt:P625 ?coord.
  OPTIONAL { ?p rdfs:label ?ja FILTER(lang(?ja)="ja") }
  OPTIONAL { ?p rdfs:label ?en FILTER(lang(?en)="en") }
  OPTIONAL { ?p wdt:P856 ?site }
  OPTIONAL { ?p wdt:P576|wdt:P3999 ?closed }
}
"""
RAILWAY_NAME = re.compile(r"鉄道|電車|汽車|機関車|リニア|新幹線|交通|ロマンスカー|railway|train|tram|rail", re.I)


def fetch():
    if CACHE.exists():
        return
    print("Querying Wikidata for railway places")
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": QUERY})
    request = urllib.request.Request(url, headers={"Accept": "text/csv", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response:
        body = response.read()
    if not body.startswith(b"p,"):
        raise SystemExit("Wikidata returned no places; try again later")
    CACHE.write_bytes(body)


def metres(a, b):
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * 111320 * math.cos(lat), (a[1] - b[1]) * 110540)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (ascii_name(text) or "").lower()).strip("-")


def kind_of(cls, ja, en):
    if "リニア" in ja or "maglev" in en.lower():
        return "maglev"
    return {"Q420962": "heritage-railway"}.get(cls, "museum")


def build(stations, report):
    """Return place records (id, kind, name, point, wikidata, website, nearest stations…)."""
    fetch()
    found = {}
    with open(CACHE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            qid = row["p"].rsplit("/", 1)[-1]
            cls = row["cls"].rsplit("/", 1)[-1]
            point = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", row["coord"])
            if not point or qid in found:
                continue
            if row["closed"]:
                found[qid] = None  # closed: never publish, even if another row repeats it
                continue
            ja, en = row["ja"], row["en"]
            # Transport museums are kept only when they are about railways, not roads or boats.
            if cls == "Q2516357" and not RAILWAY_NAME.search(ja + " " + en):
                continue
            found[qid] = {
                "wikidata": qid,
                "kind": kind_of(cls, ja, en),
                "name": {"en": en or None, "ja": ja or en or qid},
                "point": [round(float(point[1]), 5), round(float(point[2]), 5)],
                "website": row["site"] or None,
                "source": "wikidata",
            }
    places = {qid: p for qid, p in found.items() if p}

    # data/places.csv: hide or correct a Wikidata place by its id, or add a place of our own.
    with open(CURATED, encoding="utf-8") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            where = f"data/places.csv line {n}"
            qid = row["wikidata"] or None
            if row["hide"].strip().lower() in ("yes", "true", "1"):
                if qid:
                    places.pop(qid, None)
                continue
            if row["kind"] and row["kind"] not in KINDS:
                raise SystemExit(f"{where}: kind {row['kind']!r} is not one of {sorted(KINDS)}")
            key = qid or f"curated:{row['id'] or row['ja']}"
            place = places.get(key, {"wikidata": qid, "source": None, "website": None})
            place.update({k: v for k, v in {
                "kind": row["kind"] or place.get("kind"),
                "name": {"en": row["en"] or (place.get("name") or {}).get("en"), "ja": row["ja"] or (place.get("name") or {}).get("ja")},
                "website": row["website"] or place.get("website"),
                "source": row["source"] or place.get("source"),
                "checked": row["checked"] or None,
                "id": row["id"] or None,
            }.items() if v is not None})
            if row["lat"] and row["lon"]:
                place["point"] = [round(float(row["lon"]), 5), round(float(row["lat"]), 5)]
            if "point" not in place or not place.get("kind") or not place["name"].get("ja"):
                raise SystemExit(f"{where}: a new place needs kind, ja, lat and lon")
            places[key] = place

    groups = {}
    for st in stations:
        groups.setdefault(st["group"], st)
    by_id, taken = [], set()
    for key, place in sorted(places.items(), key=lambda kv: kv[1]["name"]["ja"]):
        pid = place.get("id") or slug(place["name"]["en"] or "") or key.lower().replace(":", "-")
        while pid in taken:
            pid += "-2"
        taken.add(pid)
        near = sorted(
            ((metres(place["point"], st["point"]), st) for st in groups.values()),
            key=lambda x: x[0],
        )[:3]
        record = {
            "id": pid,
            "kind": place["kind"],
            "name": place["name"],
            "point": place["point"],
            "stations": [{"id": st["id"], "metres": round(d)} for d, st in near if d <= NEAR_M],
            "website": place.get("website"),
            "wikidata": place.get("wikidata"),
            "source": place.get("source"),
            "checked": place.get("checked"),
        }
        if not record["stations"]:
            report.append(f"place {pid}: no station within {NEAR_M} m")
        by_id.append(record)
    return by_id

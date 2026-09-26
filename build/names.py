"""English names and kana readings for stations, matched from Wikidata (CC0).

N02 names stations in Japanese only. Each N02 station is matched to the nearest Wikidata station
or tram stop with the same Japanese name, within MATCH_M. data/station_names.csv overrides a
match, or fills one in, by N02 station code.
"""

import csv
import math
import re
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "sources" / "wikidata"
OVERRIDES = ROOT / "data" / "station_names.csv"
CLASSES = {"Q55488": "railway station", "Q2175765": "tram stop"}
MATCH_M = 2000
USER_AGENT = "tetsunote-api/0.1 (https://github.com/shoreless)"

QUERY = """
SELECT ?s ?ja ?en ?kana ?coord WHERE {
  ?s wdt:P17 wd:Q17; wdt:P625 ?coord; wdt:P31/wdt:P279* wd:%s.
  ?s rdfs:label ?ja FILTER(lang(?ja)="ja")
  OPTIONAL { ?s rdfs:label ?en FILTER(lang(?en)="en") }
  OPTIONAL { ?s wdt:P1814 ?kana }
}
"""


def fetch():
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    for cls in CLASSES:
        path = SOURCE_DIR / f"{cls}.csv"
        if path.exists():
            continue
        print(f"Querying Wikidata for {CLASSES[cls]}s")
        url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": QUERY % cls})
        request = urllib.request.Request(url, headers={"Accept": "text/csv", "User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=300) as response:
            body = response.read()
        if body.count(b"\n") < 2:
            raise SystemExit(f"Wikidata returned no {CLASSES[cls]}s; try again later")
        path.write_bytes(body)


def base_name(ja):
    ja = re.sub(r"[（(].*?[)）]", "", ja).strip()
    ja = ja.translate(str.maketrans("ヶヵケ", "ケカケ"))  # 霞ヶ関 and 霞ケ関 are the same name
    return re.sub(r"(駅|停留場|停留所)$", "", ja)


PREFIXES = "Shin|Higashi|Nishi|Minami|Kita|Naka|Kami|Shimo|Moto|Oku|Ko|Ō|O"


def clean_en(en):
    # Wikidata sometimes writes the hyphen as U+2010 or U+2011; a plain one is what people type.
    en = re.sub("[\u2010\u2011]", "-", en)
    en = re.sub(r"\s*\(.*?\)", "", en).strip()
    en = re.sub(r"\s+(Station|Stop|Tram Stop|Streetcar Stop)$", "", en, flags=re.I)
    # "Shin-ōtsuka" → "Shin-Ōtsuka": a place name after a prefix keeps its capital
    return re.sub(rf"\b({PREFIXES})-(\w)", lambda m: f"{m[1]}-{m[2].upper()}", en)


def ascii_name(en):
    """Otemachi for Ōtemachi: what station signs mostly show, and what people type."""
    return unicodedata.normalize("NFKD", en).encode("ascii", "ignore").decode() if en else None


def clean_kana(kana):
    return re.sub(r"(えき|ていりゅうじょう|ていりゅうしょ)$", "", kana)


def metres(a, b):
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * 111320 * math.cos(lat), (a[1] - b[1]) * 110540)


class Names:
    def __init__(self):
        fetch()
        self.items = defaultdict(dict)
        for cls in CLASSES:
            with open(SOURCE_DIR / f"{cls}.csv", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    point = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", row["coord"])
                    if not point:
                        continue
                    qid = row["s"].rsplit("/", 1)[-1]
                    item = self.items[base_name(row["ja"])].setdefault(qid, {
                        "wikidata": qid,
                        "point": (float(point[1]), float(point[2])),
                        "en": clean_en(row["en"]) if row["en"] else None,
                        "reading": clean_kana(row["kana"]) if row["kana"] else None,
                    })
                    item["reading"] = item["reading"] or (clean_kana(row["kana"]) if row["kana"] else None)
        self.overrides = {}
        if OVERRIDES.exists():
            with open(OVERRIDES, encoding="utf-8") as f:
                self.overrides = {row["id"]: row for row in csv.DictReader(f)}

    def match(self, code, ja, point):
        """Return {"en", "reading", "wikidata"} for an N02 station; values may be None."""
        found = {"en": None, "reading": None, "wikidata": None}
        near = [
            (metres(point, item["point"]), item)
            for item in self.items.get(base_name(ja), {}).values()
        ]
        near = [x for x in near if x[0] <= MATCH_M]
        if near:
            item = min(near, key=lambda x: x[0])[1]
            found = {k: item[k] for k in found}
        override = self.overrides.get(code)
        if override:
            found.update({k: v for k, v in override.items() if k in found and v})
        return found


LINE_OVERRIDES = ROOT / "data" / "lines.csv"
LINE_QUERY = """
SELECT ?s ?line ?ja ?en ?colour WHERE {
  ?s wdt:P17 wd:Q17; wdt:P81 ?line.
  ?line rdfs:label ?ja FILTER(lang(?ja)="ja")
  OPTIONAL { ?line rdfs:label ?en FILTER(lang(?en)="en") }
  OPTIONAL { ?line wdt:P465 ?colour }
}
"""
MIN_SHARE = 0.6  # at least this share of a line's stations must be on the Wikidata line…
MIN_LIKENESS = 0.6  # …or the names must be this alike


def line_core(ja):
    ja = re.sub(r"^\d+号線", "", ja)
    ja = re.sub(r"[（(].*?[)）]", "", ja)
    return re.sub(r"(本線|線)$", "", ja)


class LineNames:
    """English names for N02's legal lines, found through the Wikidata lines their stations serve."""

    def __init__(self):
        path = SOURCE_DIR / "station-lines-v2.csv"
        if not path.exists():
            print("Querying Wikidata for station lines")
            url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": LINE_QUERY})
            request = urllib.request.Request(url, headers={"Accept": "text/csv", "User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=300) as response:
                body = response.read()
            if body.count(b"\n") < 2:
                raise SystemExit("Wikidata returned no station lines; try again later")
            path.write_bytes(body)
        self.lines_of = defaultdict(set)
        self.info = {}
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                station, line = (row[k].rsplit("/", 1)[-1] for k in ("s", "line"))
                self.lines_of[station].add(line)
                colour = row["colour"].strip().lstrip("#").upper()
                colour = f"#{colour}" if re.fullmatch(r"[0-9A-F]{6}", colour) else None
                ja, en, known = self.info.get(line, (row["ja"], row["en"], None))
                self.info[line] = (ja, en, known or colour)
        self.overrides = {}
        if LINE_OVERRIDES.exists():
            with open(LINE_OVERRIDES, encoding="utf-8") as f:
                self.overrides = {(r["operator"], r["line"]): r for r in csv.DictReader(f)}

    def match(self, operator_ja, line_ja, station_qids):
        """Return {"en", "colour", "wikidata", "id"}; "id" is set only by an override."""
        from difflib import SequenceMatcher

        found = {"en": None, "colour": None, "wikidata": None, "id": None}
        counts = defaultdict(int)
        for qid in station_qids:
            for line in self.lines_of.get(qid, ()):
                counts[line] += 1
        if counts:
            total = max(len(station_qids), 1)
            likeness = {
                line: SequenceMatcher(None, line_core(line_ja), line_core(self.info[line][0])).ratio()
                for line in counts
            }
            best = max(counts, key=lambda l: counts[l] / total + likeness[l])
            if counts[best] / total >= MIN_SHARE or likeness[best] >= MIN_LIKENESS:
                en = clean_line_en(self.info[best][1]) if self.info[best][1] else None
                if en and re.search(r"(分岐線|支線)$", line_ja) and "Branch" not in en:
                    en += " Branch"
                found = {"en": en, "colour": self.info[best][2], "wikidata": best, "id": None}
        override = self.overrides.get((operator_ja, line_ja))
        if override:
            found.update({k: v for k, v in override.items() if k in found and v})
        return found


def clean_line_en(en):
    en = re.sub("[\u2010\u2011]", "-", en)
    en = re.sub(r"\s*\(.*?\)", "", en).strip()
    return en[0].upper() + en[1:] if en else en


def line_slug_en(en, operator_en):
    """Chūō Main Line → chuo; Keiō Inokashira Line (Keio Corporation) → inokashira."""
    words = ascii_name(en).lower().replace("'", "")
    words = re.sub(r"\b(main )?line\b", "", words)
    for prefix in (ascii_name(operator_en) or "").lower().split()[:1]:
        rest = re.sub(rf"^{re.escape(prefix)}\b", "", words)
        words = rest if rest.strip() else words  # Keio Line stays keio
    slug = re.sub(r"[^a-z0-9]+", "-", words).strip("-")
    return slug or "main"

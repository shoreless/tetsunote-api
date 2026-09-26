"""Services (運転系統): the trains riders board, as opposed to the legal lines (路線) the track is filed under.

A legal line and a service often differ. 中央線 carries both 中央線快速 and 中央・総武線各駅停車, and
湘南新宿ライン runs over 東北線, 山手線 and 東海道線. data/services.csv names each service;
data/service_sections.csv gives its track as sections along legal lines, each from station to station
through waypoints (`via`, Japanese names joined by `>`), so a section follows the branch the trains use.
A section's `stops` is `all`, or the names of its stops separated by spaces, or empty to take them from
Wikipedia: the section's own `wikipedia_ja` article if it names one, else the service's.

Which stations a service stops at comes from the station table (駅一覧) of its Japanese Wikipedia
article: the stations on its sections that the table marks as served. The facts are taken, not the
text; articles are cached in sources/wikipedia/services/. A section with `stops` set to `all` stops at
every station on it, as does a service with no article.

data/through.csv lists where trains of one line run on into another without the rider changing,
like 東西線 into 中央線 at 中野. The app treats a ride on either as able to carry on into the other.

Written to v0/services.json.
"""

import csv
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from borrow import path as line_path
from names import USER_AGENT

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "sources" / "wikipedia" / "services"
WIKIDATA = ROOT / "sources" / "wikidata" / "services.json"
# Stop marks in Wikipedia station tables; ｜ (passes) and ■ (colour swatches in notes) are not stops.
STOP_MARKS = set("●◆▲△○◇◎★")


def norm(name):
    """A station name as both our data and Wikipedia spell it: no 駅, no qualifier, ヶ for ケ between kanji."""
    name = re.sub(r"\s*[（(〈<].*?[）)〉>]", "", name).strip()
    name = re.sub(r"駅$", "", name)
    return re.sub(r"(?<=[一-鿿])[ケヵ](?=[一-鿿])", "ヶ", name)


def wikitext(title):
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{title}.txt"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    query = urllib.parse.urlencode({"action": "parse", "page": title, "prop": "wikitext", "format": "json", "redirects": 1})
    request = urllib.request.Request(f"https://ja.wikipedia.org/w/api.php?{query}", headers={"User-Agent": USER_AGENT})
    text = json.load(urllib.request.urlopen(request, timeout=60))["parse"]["wikitext"]["*"]
    cached.write_text(text, encoding="utf-8")
    time.sleep(1)
    return text


def served(title):
    """Stations the article's 駅一覧 marks as served, by normalised name; None if it has no such table."""
    text = wikitext(title)
    start = re.search(r"^==\s*駅一覧\s*==", text, re.M)
    if not start:
        return None
    rest = text[start.end():]
    end = re.search(r"^==[^=]", rest, re.M)
    section = rest[: end.start()] if end else rest
    stops, listed = set(), set()
    for table in re.findall(r"\{\|.*?\n\|\}", section, re.S):
        rows = []
        for row in re.split(r"\n\|-", table):
            cells = [c.strip() for c in row.split("\n") if c.startswith("|") and not c.startswith("|}")]
            station = None
            for cell in cells:
                body = cell.lstrip("|").split("|", 1)[-1] if cell.count("|") > 1 and "[[" not in cell.split("|", 2)[1] else cell.lstrip("|")
                found = re.search(r"\[\[([^\]|]*?駅[^\]|]*?)(?:\|([^\]]*))?\]\]", body)
                if found and "駅" in (found.group(2) or found.group(1)):
                    station = norm(found.group(2) or found.group(1))
                    parenthesised = body.strip().startswith(("（", "("))
                    break
            if not station:
                continue
            marks = set("".join(c.split("|")[-1] for c in cells if len(c.split("|")[-1].strip()) <= 2))
            rows.append((station, marks & STOP_MARKS, parenthesised, bool(marks & set("｜|↓↑"))))
        # The columns mark the faster trains (快速, 特別快速); the service's slowest trains stop at every
        # station listed, and stations without a platform on its tracks are listed in brackets.
        for station, stop, parenthesised, passes in rows:
            listed.add(station)
            if not parenthesised:
                stops.add(station)
    return stops if listed else None


def wikidata(ids):
    cache = json.loads(WIKIDATA.read_text(encoding="utf-8")) if WIKIDATA.exists() else {}
    missing = [i for i in ids if i and i not in cache]
    for start in range(0, len(missing), 40):
        batch = missing[start:start + 40]
        query = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(batch), "props": "labels|claims",
                                        "languages": "ja|en", "format": "json"})
        request = urllib.request.Request(f"https://www.wikidata.org/w/api.php?{query}", headers={"User-Agent": USER_AGENT})
        for qid, entity in json.load(urllib.request.urlopen(request, timeout=60))["entities"].items():
            colours = [c["mainsnak"].get("datavalue", {}).get("value") for c in entity.get("claims", {}).get("P465", [])]
            cache[qid] = {
                "ja": entity.get("labels", {}).get("ja", {}).get("value"),
                "en": entity.get("labels", {}).get("en", {}).get("value"),
                "colour": next((c for c in colours if c), None),
            }
    WIKIDATA.parent.mkdir(parents=True, exist_ok=True)
    WIKIDATA.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return cache


def build(shards, report):
    lines = {line["id"]: (shard, line) for shard in shards.values() for line in shard["lines"]}

    def on_line(line_id, name, where):
        shard, line = lines[line_id]
        ends = {x for seg in line["segments"] for x in (seg["from"], seg["to"])}
        found = [s for s in shard["stations"].values() if s["id"] in ends and norm(s["name"]["ja"]) == norm(name)]
        if len(found) != 1:
            raise SystemExit(f"{where}: {name} is {'not' if not found else 'more than once'} on {line_id}")
        return found[0]

    rows = list(csv.DictReader((ROOT / "data" / "services.csv").open(encoding="utf-8")))
    facts = wikidata([r["wikidata"] for r in rows])
    sections = {}
    for n, row in enumerate(csv.DictReader((ROOT / "data" / "service_sections.csv").open(encoding="utf-8")), start=2):
        sections.setdefault(row["service"], []).append((n, row))

    services = []
    for row in rows:
        where = f"data/services.csv {row['id']}"
        if row["id"] not in sections:
            raise SystemExit(f"{where}: no sections")
        stops_named = served(row["wikipedia_ja"]) if row["wikipedia_ja"] else None
        if row["wikipedia_ja"] and stops_named is None:
            report.append(f"services: {row['id']}: no station table in ja:{row['wikipedia_ja']}; every station counts as a stop")
        out_sections, on_path = [], set()
        for n, section in sections[row["id"]]:
            here = f"data/service_sections.csv line {n}"
            if section["line"] not in lines:
                raise SystemExit(f"{here}: unknown line {section['line']}")
            points = [on_line(section["line"], name, here) for name in section["via"].split(">")]
            segments, order = [], [points[0]["id"]]
            for a, b in zip(points, points[1:]):
                leg = line_path(lines[section["line"]][1], a["id"], b["id"])
                if leg is None:
                    raise SystemExit(f"{here}: no track on {section['line']} from {a['name']['ja']} to {b['name']['ja']}")
                for seg in leg:
                    segments.append(seg["id"])
                    order.append(seg["to"] if seg["from"] == order[-1] else seg["from"])
            stations = lines[section["line"]][0]["stations"]
            names = [stations[s]["name"]["ja"] for s in order]
            on_path |= {norm(x) for x in names}
            # Stops: every station, a list of names, or the stations the article (the section's own, if
            # it names one, else the service's) marks as served.
            table = served(section["wikipedia_ja"]) if section.get("wikipedia_ja") else stops_named
            if section["stops"] == "all" or (not section["stops"] and table is None):
                stops = order
            elif section["stops"]:
                wanted = {norm(x) for x in section["stops"].split()}
                unknown = wanted - {norm(x) for x in names}
                if unknown:
                    raise SystemExit(f"{here}: stops not on the section: {' '.join(sorted(unknown))}")
                stops = [s for s, name in zip(order, names) if norm(name) in wanted]
            else:
                stops = [s for s, name in zip(order, names) if norm(name) in table]
            out_sections.append({
                "line": section["line"], "from": order[0], "to": order[-1],
                "segments": segments, "stops": list(dict.fromkeys(stops)),
            })
        if stops_named:
            beyond = sorted(stops_named - on_path)
            if beyond:
                report.append(f"services: {row['id']}: served beyond its sections (not in the app): {' '.join(beyond)}")
        fact = facts.get(row["wikidata"], {})
        colour = row["colour"] or fact.get("colour")
        if not colour:
            report.append(f"services: {row['id']}: no colour")
        services.append({
            "id": row["id"],
            "name": {"ja": row["name_ja"], "en": row["name_en"]},
            "kind": row["kind"],
            "colour": f"#{colour.upper()}" if colour else None,
            "trains": {"ja": row["trains_ja"], "en": row["trains_en"]} if row["trains_ja"] else None,
            # The train models that run this service, where it has its own (スペーシアX is the N100).
            "series": row["series"].split() if row.get("series") else [],
            "wikidata": row["wikidata"] or None,
            "sections": out_sections,
        })

    through = []
    for n, row in enumerate(csv.DictReader((ROOT / "data" / "through.csv").open(encoding="utf-8")), start=2):
        here = f"data/through.csv line {n}"
        for key in ("line_a", "line_b"):
            if row[key] not in lines:
                raise SystemExit(f"{here}: unknown line {row[key]}")
        a = on_line(row["line_a"], row["station"], here)
        b = on_line(row["line_b"], row["station"], here)
        if a["group"] != b["group"]:
            report.append(f"services: {here}: {row['station']} is not one station on both lines ({a['group']}, {b['group']})")
        through.append({"lines": [row["line_a"], row["line_b"]], "stations": [a["id"], b["id"]]})

    return {
        "version": 0,
        "languages": ["en", "ja"],
        "stops_source": "Japanese Wikipedia station tables (駅一覧), facts only",
        "services": services,
        "through": through,
    }

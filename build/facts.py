"""Facts about train models from Wikidata (CC0), in English and Japanese.

For each model with a Wikidata id: when it entered and left service, top speed, car length, how many
were built, who built it, what it replaced and what replaced it, a one-line description, and its
Wikipedia articles. Entities are cached in sources/wikidata/entities.json; delete it to refresh.
"""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from names import USER_AGENT

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "sources" / "wikidata" / "entities.json"
API = "https://www.wikidata.org/w/api.php"

KMH = {"Q180154": 1.0, "Q211256": 1.609344}  # km/h, mph
METRES = {"Q11573": 1.0, "Q174728": 0.01, "Q174789": 0.001}  # m, cm, mm


def fetch(ids, cache):
    missing = [i for i in ids if i not in cache]
    for start in range(0, len(missing), 50):
        batch = missing[start:start + 50]
        query = urllib.parse.urlencode({
            "action": "wbgetentities", "ids": "|".join(batch), "format": "json",
            "props": "labels|descriptions|claims|sitelinks", "languages": "en|ja",
            "sitefilter": "enwiki|jawiki",
        })
        request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            cache.update(json.load(response)["entities"])
        time.sleep(0.5)


def values(entity, prop):
    out = []
    for claim in entity.get("claims", {}).get(prop, []):
        if claim.get("rank") == "deprecated":
            continue
        value = claim["mainsnak"].get("datavalue", {}).get("value")
        if value is not None:
            out.append(value)
    return out


def text(entity, key, lang):
    return entity.get(key, {}).get(lang, {}).get("value")


def year(value):
    # "+2015-11-30T00:00:00Z" with a precision; keep what is known: a year, or a full date.
    time_ = value["time"].lstrip("+")
    return time_[:10] if value.get("precision", 9) >= 11 else time_[:4]


def quantity(value, units):
    unit = value.get("unit", "").rsplit("/", 1)[-1]
    if unit not in units:
        return None
    return round(float(value["amount"]) * units[unit], 1)


def build(series, report):
    """Add facts, description and links to each series record that has a Wikidata id."""
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    ids = sorted({s["wikidata"] for s in series if s["wikidata"]})
    fetch(ids, cache)
    referenced = set()
    for qid in ids:
        entity = cache.get(qid, {})
        for prop in ("P176", "P1365", "P1366"):
            referenced |= {v["id"] for v in values(entity, prop)}
    fetch(sorted(referenced), cache)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    by_qid = {s["wikidata"]: s["id"] for s in series if s["wikidata"]}

    def named(qid):
        entity = cache.get(qid, {})
        return {"en": text(entity, "labels", "en"), "ja": text(entity, "labels", "ja") or text(entity, "labels", "en") or qid}

    def related(qid):
        return {"series": by_qid.get(qid), "name": named(qid)}

    for record in series:
        qid = record["wikidata"]
        entity = cache.get(qid) if qid else None
        if not entity or "missing" in entity:
            record.update(facts=None, description=None, links=None, replaces=[], replaced_by=[])
            continue
        entered = [year(v) for v in values(entity, "P729")]
        retired = [year(v) for v in values(entity, "P730")]
        speeds = [q for q in (quantity(v, KMH) for v in values(entity, "P2052")) if q]
        lengths = [q for q in (quantity(v, METRES) for v in values(entity, "P2043")) if q]
        built = [int(float(v["amount"])) for v in values(entity, "P1092")]
        record["facts"] = {
            "entered_service": min(entered) if entered else None,
            "retired": max(retired) if retired else None,
            "top_speed_kmh": max(speeds) if speeds else None,
            "car_length_m": max(lengths) if lengths else None,
            "built": max(built) if built else None,
            "manufacturers": [named(v["id"]) for v in values(entity, "P176")],
        }
        record["description"] = {"en": text(entity, "descriptions", "en"), "ja": text(entity, "descriptions", "ja")}
        record["replaces"] = [related(v["id"]) for v in values(entity, "P1365")]
        record["replaced_by"] = [related(v["id"]) for v in values(entity, "P1366")]
        sitelinks = entity.get("sitelinks", {})
        record["links"] = {
            "wikidata": f"https://www.wikidata.org/wiki/{qid}",
            "wikipedia_ja": wiki_url("ja", sitelinks.get("jawiki", {}).get("title")),
            "wikipedia_en": wiki_url("en", sitelinks.get("enwiki", {}).get("title")),
        }
        # A model we call active that Wikidata says was retired, or entered service long ago, is
        # probably matched to an older model of the same name: pin the right item in series.csv.
        if record["status"] == "active" and record["facts"]["retired"]:
            report.append(f"series {record['id']}: active here, but Wikidata {qid} says retired {record['facts']['retired']}")


def wiki_url(lang, title):
    if not title:
        return None
    return f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))


def titles(record):
    """{lang: article title} for a record built above."""
    links = record.get("links") or {}
    out = {}
    for lang in ("ja", "en"):
        url = links.get(f"wikipedia_{lang}")
        if url:
            out[lang] = urllib.parse.unquote(url.rsplit("/wiki/", 1)[1]).replace("_", " ")
    return out


def entities():
    """The cached Wikidata entities, after build() has run."""
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def build_lines(lines, report):
    """Add facts, description and links to each line that has a Wikidata id.

    Lines are legal lines matched to the Wikidata line most of their stations serve, so facts such as
    length describe that whole line: JR East's part of the Chūō Main Line gets the whole line's length.
    """
    cache = entities()
    ids = sorted({l["wikidata"] for l in lines if l.get("wikidata")})
    fetch(ids, cache)
    referenced = set()
    for qid in ids:
        entity = cache.get(qid, {})
        for prop in ("P1064", "P930"):
            referenced |= {v["id"] for v in values(entity, prop)}
    fetch(sorted(referenced), cache)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    def named(qid):
        entity = cache.get(qid, {})
        return {"en": text(entity, "labels", "en"), "ja": text(entity, "labels", "ja") or text(entity, "labels", "en") or qid}

    for line in lines:
        qid = line.get("wikidata")
        entity = cache.get(qid) if qid else None
        if not entity or "missing" in entity:
            line.update(facts=None, description=None, links=None)
            continue
        opened = [year(v) for v in values(entity, "P1619")]
        lengths = [q for q in (quantity(v, {"Q828224": 1.0, "Q11573": 0.001}) for v in values(entity, "P2043")) if q]
        speeds = [q for q in (quantity(v, KMH) for v in values(entity, "P2052")) if q]
        line["facts"] = {
            "opened": min(opened) if opened else None,
            "length_km": max(lengths) if lengths else None,
            "top_speed_kmh": max(speeds) if speeds else None,
            "gauge": [named(v["id"]) for v in values(entity, "P1064")],
            "electrification": [named(v["id"]) for v in values(entity, "P930")],
        }
        line["description"] = {"en": text(entity, "descriptions", "en"), "ja": text(entity, "descriptions", "ja")}
        sitelinks = entity.get("sitelinks", {})
        line["links"] = {
            "wikidata": f"https://www.wikidata.org/wiki/{qid}",
            "wikipedia_ja": wiki_url("ja", sitelinks.get("jawiki", {}).get("title")),
            "wikipedia_en": wiki_url("en", sitelinks.get("enwiki", {}).get("title")),
        }

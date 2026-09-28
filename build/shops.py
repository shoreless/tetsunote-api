"""Railway shops for fans: model railway shops, railway bookshops, operators' goods shops, parts shops.

Listed by hand in data/shops.csv from each shop's own website: the name, the street address, the
site, and a short note in our own words. Each address is placed on the map with the Geospatial
Information Authority of Japan's address search (国土地理院), cached in sources/gsi/geocode.json;
a row's own lat and lon win over it. Shops are published as places of kind "shop".
"""

import csv
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from names import USER_AGENT

ROOT = Path(__file__).resolve().parent.parent
LIST = ROOT / "data" / "shops.csv"
CACHE = ROOT / "sources" / "gsi" / "geocode.json"
SEARCH = "https://msearch.gsi.go.jp/address-search/AddressSearch?q="


def street(address):
    """The address down to its block number, without the building: what the address search knows."""
    address = re.sub(r"[０-９]", lambda m: chr(ord(m[0]) - 0xFEE0), address)
    address = address.replace("−", "-").replace("ー", "-").replace("‐", "-").replace("－", "-")
    m = re.match(r"^(.*?\d+(?:丁目|番地?|-)\s*\d*(?:番地?|号|-)?\s*\d*(?:号)?)", address)
    return (m[1] if m else address).strip(" -")


def geocode(address, cache):
    key = street(address)
    if key not in cache:
        request = urllib.request.Request(SEARCH + urllib.parse.quote(key), headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            found = json.load(response)
        cache[key] = found[0]["geometry"]["coordinates"] if found else None
        time.sleep(0.3)
    return cache[key]


def load(report):
    """Shops as place records keyed "shop:<id>", with their point, ready for places.build."""
    if not LIST.exists():
        return {}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    shops = {}
    with open(LIST, encoding="utf-8") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            where = f"data/shops.csv line {n}"
            if row.get("hide", "").strip().lower() in ("yes", "true", "1"):
                continue
            if not row["id"] or not row["ja"] or not row["address"]:
                raise SystemExit(f"{where}: a shop needs id, ja and address")
            if f"shop:{row['id']}" in shops:
                raise SystemExit(f"{where}: id {row['id']} is used twice")
            if row["lat"] and row["lon"]:
                point = [float(row["lon"]), float(row["lat"])]
            else:
                point = geocode(row["address"], cache)
                if not point:
                    report.append(f"{where}: {row['ja']}: address not found ({street(row['address'])}); left out")
                    continue
            shops[f"shop:{row['id']}"] = {
                "id": row["id"],
                "kind": row.get("kind") or "shop",
                "name": {"en": row["en"] or None, "ja": row["ja"]},
                "point": [round(point[0], 5), round(point[1], 5)],
                "website": row["website"] or None,
                "source": row["source"] or row["website"] or None,
                "checked": row["checked"] or None,
                "chain": row["chain"] or None,
                "address": row["address"],
                "description": {"en": row["note_en"] or None, "ja": row["note_ja"] or None},
                "wikidata": None,
            }
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    return shops

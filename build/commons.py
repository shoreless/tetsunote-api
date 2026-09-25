"""Photos from Wikimedia Commons for train models that have no picture of their own.

Each model's Wikidata item names a photo (P18). Only freely licensed photos are used (CC BY, CC BY-SA,
CC0, public domain), and each keeps its author, licence and file page so apps can credit it.
Metadata and downloads are cached in sources/commons/.
"""

import hashlib
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from names import USER_AGENT

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "sources" / "commons"
API = "https://commons.wikimedia.org/w/api.php"
FREE = re.compile(r"^(CC BY(-SA)? \d(\.\d)?.*|CC0.*|Public domain|PD.*)$", re.I)


def claim_file(entity):
    for claim in entity.get("claims", {}).get("P18", []):
        value = claim["mainsnak"].get("datavalue", {}).get("value")
        if value and claim.get("rank") != "deprecated":
            return value
    return None


def plain(text):
    text = re.sub(r"<[^>]+>", "", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()[:120] or None


def metadata(files):
    path = CACHE / "meta.json"
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    missing = [f for f in files if f not in cache]
    for start in range(0, len(missing), 40):
        batch = missing[start:start + 40]
        query = urllib.parse.urlencode({
            "action": "query", "format": "json", "prop": "imageinfo",
            "titles": "|".join("File:" + f for f in batch),
            "iiprop": "url|extmetadata", "iiurlwidth": 1200,
            "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl",
        })
        request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.load(response)["query"]
        names = {n["to"]: n["from"] for n in data.get("normalized", [])}
        for page in data["pages"].values():
            name = names.get(page["title"], page["title"]).removeprefix("File:")
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata", {})
            cache[name] = {
                "thumb": info.get("thumburl"),
                "page": info.get("descriptionurl"),
                "artist": plain(meta.get("Artist", {}).get("value")),
                "licence": plain(meta.get("LicenseShortName", {}).get("value")),
                "licence_url": meta.get("LicenseUrl", {}).get("value"),
            }
        time.sleep(0.5)
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    return cache


def download(url):
    target = CACHE / "files" / (hashlib.sha1(url.encode()).hexdigest() + Path(urllib.parse.urlparse(url).path).suffix)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            target.write_bytes(response.read())
        time.sleep(0.3)
    return target


def photos(series, entities, pictured, report):
    """Rows for images.build: one Commons photo for each model without a picture of its own."""
    wanted = {}
    for record in series:
        entity = entities.get(record["wikidata"] or "", {})
        name = claim_file(entity)
        if record["id"] not in pictured and name:
            wanted[record["id"]] = name
    meta = metadata(sorted(set(wanted.values())))
    rows, skipped = [], []
    for series_id, name in sorted(wanted.items()):
        m = meta.get(name) or {}
        if not m.get("thumb") or not m.get("licence") or not FREE.match(m["licence"]):
            skipped.append(f"{series_id} ({m.get('licence') or 'no licence'})")
            continue
        rows.append({
            "series": series_id,
            "path": download(m["thumb"]),
            "generated": False,
            "credit": f"{m['artist'] or 'Unknown author'} / Wikimedia Commons",
            "licence": m["licence"],
            "licence_url": m["licence_url"],
            "source_url": m["page"],
            "note": None,
        })
    if skipped:
        report.append("Commons photos not used (licence): " + ", ".join(skipped))
    return rows

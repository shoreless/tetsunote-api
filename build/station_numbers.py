"""Station numbers (駅ナンバリング): JY 13, M 25, KK 01, from each station's Japanese Wikipedia infobox.

Wikidata has numbers for few stations and almost none of JR East's, but every station article's
{{駅情報}} infobox pairs each line with its number: 所属路線N and 駅番号N, the number written as
{{駅番号r|JY|13|#9acd32|1}} (prefix, number, colour, shape). A number is a fact, not prose, so it is
published with the rest of the data.

Each number is matched to one of our lines at that station: through a service whose article the
infobox links to (京浜東北線 on the 東北線 track), else a line of the same name, else the same colour.
Numbers that match nothing stay on the station with no line, so its page can still show them.

Article titles come from the stations' Wikidata sitelinks. The infoboxes' wikitext is cached in
sources/wikipedia/station-infoboxes-ja.json, so parsing can change without fetching again; delete it
to refresh.
"""

import csv
import gzip
import json
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from names import USER_AGENT, line_core

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "sources" / "wikipedia" / "station-infoboxes-ja.json"
SITELINKS = ROOT / "sources" / "wikidata" / "station-articles.csv"

# {{駅番号r}}'s shape argument, as the template draws it.
SHAPES = {"1": "square", "2": "round-square", "3": "round-square", "4": "circle", "5": "square", "6": "circle"}


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read()
        return gzip.decompress(body) if response.headers.get("Content-Encoding") == "gzip" else body


def sitelinks(qids):
    """Each station item's ja Wikipedia article title, by Wikidata id."""
    found = {}
    if SITELINKS.exists():
        with open(SITELINKS, encoding="utf-8") as f:
            found = {row["qid"]: row["title"] for row in csv.DictReader(f)}
    missing = sorted(set(qids) - found.keys())
    for i in range(0, len(missing), 300):
        chunk = missing[i:i + 300]
        query = "SELECT ?s ?title WHERE { VALUES ?s { %s } ?a schema:about ?s; schema:isPartOf <https://ja.wikipedia.org/>; schema:name ?title }" % " ".join(f"wd:{q}" for q in chunk)
        body = get("https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": query, "format": "json"}))
        for b in json.loads(body)["results"]["bindings"]:
            found[b["s"]["value"].rsplit("/", 1)[-1]] = b["title"]["value"]
        for q in chunk:
            found.setdefault(q, "")
        time.sleep(1)
    SITELINKS.parent.mkdir(parents=True, exist_ok=True)
    with open(SITELINKS, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["qid", "title"])
        w.writeheader()
        w.writerows({"qid": q, "title": t} for q, t in sorted(found.items()))
    return {q: t for q, t in found.items() if t}


def strip_refs(text):
    text = re.sub(r"<ref[^>]*/>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


NAMED = {"black": "#000000", "green": "#00a54f", "orange": "#f7931d", "blue": "#0072bc", "red": "#ed1c23",
         "white": "#ffffff", "purple": "#800080", "yellow": "#ffd400", "brown": "#8b4513", "gray": "#808080",
         "grey": "#808080", "pink": "#ff69b4", "skyblue": "#87ceeb", "navy": "#000080"}


def colour_of(value):
    """#9acd32 from 9acd32, #9ACD32, #e51 or green; None for anything else."""
    v = (value or "").strip().lower()
    if v in NAMED:
        return NAMED[v]
    v = v.lstrip("#")
    if re.fullmatch(r"[0-9a-f]{3}", v):
        v = "".join(c * 2 for c in v)
    return f"#{v}" if re.fullmatch(r"[0-9a-f]{6}", v) else None


def template_args(text, name_pattern):
    """The positional arguments of each {{name|…}} in text, nested templates left whole."""
    out = []
    for m in re.finditer(r"\{\{\s*(%s)\s*\|" % name_pattern, text):
        depth, i, start, args = 1, m.end(), m.end(), []
        while i < len(text) and depth:
            if text.startswith("{{", i):
                depth += 1; i += 2; continue
            if text.startswith("}}", i):
                depth -= 1
                if depth == 0:
                    args.append(text[start:i])
                i += 2; continue
            if text[i] == "|" and depth == 1:
                args.append(text[start:i]); start = i + 1
            i += 1
        out.append([a.strip() for a in args])
    return out


def infoboxes(wikitext):
    """The article's {{駅情報}} templates, whole, without references."""
    text = strip_refs(wikitext)
    found = []
    for m in re.finditer(r"\{\{\s*駅情報", text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            if text.startswith("{{", i):
                depth += 1; i += 2
            elif text.startswith("}}", i):
                depth -= 1; i += 2
            else:
                i += 1
        found.append(text[m.start():i])
    return "\n".join(found)


def parse(text):
    """[{operator, entries: [{link, prefix, number, colour, shape}]}] for each {{駅情報}} in the text."""
    blocks = []
    for start in [m.end() for m in re.finditer(r"\{\{\s*駅情報", text)]:
        # The template's parameters: split at the |s that belong to it, not to templates or links inside.
        parts, depth, i, begin = [], 0, start, start
        while i < len(text):
            two = text[i:i + 2]
            if two in ("{{", "[["):
                depth += 1; i += 2; continue
            if two in ("}}", "]]"):
                if depth == 0:
                    break
                depth -= 1; i += 2; continue
            if text[i] == "|" and depth == 0:
                parts.append(text[begin:i]); begin = i + 1
            i += 1
        parts.append(text[begin:i])
        params = {}
        for part in parts:
            key, eq, value = part.partition("=")
            # A key can come twice, the second for a former line and often empty: keep what has a value.
            if eq and not params.get(key.strip()):
                params[key.strip()] = value.strip()
        operator = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", params.get("所属事業者", "")).strip()
        entries = []
        for key, value in params.items():
            m = re.fullmatch(r"駅番号(\d*)", key)
            if not m:
                continue
            line_value = params.get(f"所属路線{m[1]}", "")
            link = re.search(r"\[\[([^|\]]+)", line_value)
            found = []
            # {{駅番号r|JY|13|#9acd32|1}}, or an operator's own: {{JR海駅番号|CA|66}}, {{近鉄駅番号|A|26}}.
            for args in template_args(value, r"[^|{}]*?駅番号[rcs]?"):
                args = [a for a in args if "=" not in a]
                if len(args) >= 2 and re.fullmatch(r"(JR-)?[A-Za-z]{1,3}", args[0]):
                    colour = args[2] if len(args) > 2 else ""
                    found.append((args[0], args[1], colour, args[3] if len(args) > 3 else ""))
                    continue
                # Colour first and the code whole: {{駅番号c|#ed1c23|S15}}, {{駅番号s|#e5171f|white|M23}}.
                whole = next((a for a in args if re.fullmatch(r"(JR-)?[A-Za-z]{1,3}-?\s?\d{1,3}", a)), None)
                if whole:
                    n = re.fullmatch(r"((?:JR-)?[A-Za-z]{1,3})-?\s?(\d{1,3})", whole)
                    found.append((n[1], n[2], args[0], "4" if "駅番号s" in value else ""))
            if not found:
                # Written out plainly, as JR West does: JR-Q17, and elsewhere KK01 or M 25.
                plain = re.sub(r"\{\{.*?\}\}", "", value)
                for n in re.finditer(r"(?<![A-Za-z])((?:JR-)?[A-Z]{1,3})[-\s]?(\d{1,3})(?!\d)", plain):
                    found.append((n[1], n[2], "", ""))
            for prefix, number, colour, shape in found:
                number = re.sub(r"[\s']", "", number)
                if not re.fullmatch(r"\d{1,3}(-\d{1,2})?[A-Za-z]?", number):
                    continue
                entries.append({
                    "link": link[1].strip() if link else None,
                    "prefix": prefix.upper(),
                    "number": number,
                    "colour": colour_of(colour),
                    "shape": SHAPES.get(shape, "square"),
                })
        if entries:
            blocks.append({"operator": operator, "entries": entries})
    return blocks


def fetch(titles):
    """Infobox wikitext by article title, fetched fifty articles at a time and cached."""
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    missing = sorted(set(titles) - cache.keys())
    for i in range(0, len(missing), 50):
        chunk = missing[i:i + 50]
        query = urllib.parse.urlencode({
            "action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "redirects": 1,
            "format": "json", "formatversion": 2, "titles": "|".join(chunk), "maxlag": 5,
        })
        # A batch too big for one response comes back in parts: follow "continue" for the rest.
        extra = {}
        while True:
            reply = json.loads(get(f"https://ja.wikipedia.org/w/api.php?{query}&" + urllib.parse.urlencode(extra)))
            data = reply["query"]
            renamed = {r["to"]: r["from"] for r in data.get("redirects", [])}
            renamed.update({n["to"]: n["from"] for n in data.get("normalized", [])})
            for page in data.get("pages", []):
                title = renamed.get(page["title"], page["title"])
                revs = page.get("revisions")
                if revs:
                    cache[title] = infoboxes(revs[0]["slots"]["main"]["content"])
            if "continue" not in reply:
                break
            extra = reply["continue"]
            time.sleep(0.5)
        for t in chunk:
            cache.setdefault(t, "")
        if i % 1000 == 0:
            print(f"  station articles {i + len(chunk)}/{len(missing)}")
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        time.sleep(0.5)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return cache


def core(title):
    """A linked line title as a comparable name: 東海道線 (JR東日本) → 東海道, 東京メトロ丸ノ内線 → 丸ノ内."""
    title = re.sub(r"\s*[（(].*?[)）]", "", title or "")
    title = re.sub(r"^(JR|東京メトロ|都営地下鉄|都営|京急|京王|小田急|東急|西武|東武|京成|京阪|阪急|阪神|近鉄|南海|名鉄|西鉄|大阪メトロ|Osaka Metro)", "", title)
    return line_core(title)


def build(shards, services, report):
    """Add "numbers" to each station: [{code, prefix, number, colour, shape, line, service}]."""
    stations = [s for shard in shards.values() for s in shard["stations"].values()]
    lines = {l["id"]: l for shard in shards.values() for l in shard["lines"]}
    operator_of = {l["id"]: shard["operator"]["name"]["ja"] for shard in shards.values() for l in shard["lines"]}
    by_group = defaultdict(list)
    for s in stations:
        by_group[s["group"]].append(s)
    titles = sitelinks({s["wikidata"] for s in stations if s["wikidata"]})
    parsed = {t: parse(raw) for t, raw in fetch(set(titles.values())).items()}

    # Services by the article that describes them, and the stations each stops at.
    with open(ROOT / "data" / "services.csv", encoding="utf-8") as f:
        articles = {row["id"]: row["wikipedia_ja"] for row in csv.DictReader(f)}
    svc_by_title = {}
    for svc in services:
        for t in filter(None, [svc["name"]["ja"], articles.get(svc["id"])]):
            svc_by_title[core(t)] = svc

    def service_line(svc, group_stations):
        """The line of ours the service runs on here; where it runs on several (山手線 at 品川 is on both
        東海道線 and 山手線 track), the one of its own name."""
        found = [s["line"] for section in svc.get("sections", []) for s in group_stations
                 if s["line"] == section["line"] and s["id"] in section.get("stops", [])]
        named = [l for l in found if core(lines[l]["name"]["ja"]) == core(svc["name"]["ja"])]
        return (named or found or [None])[0]

    numbered = 0
    for s in stations:
        s.setdefault("numbers", [])
    by_title = defaultdict(list)
    for s in stations:
        if titles.get(s["wikidata"]):
            by_title[titles[s["wikidata"]]].append(s)
    done_groups = set()
    for title, here in by_title.items():
        # One article covers the physical station: every line of its groups, whichever item each matched.
        groups = {x["group"] for x in here} - done_groups
        if not groups:
            continue
        done_groups |= groups
        group_stations = [x for g in groups for x in by_group[g]]
        seen = set()
        for block in parsed.get(title, []):
            for e in block["entries"]:
                code = f"{e['prefix']}{e['number']}"
                # One number can serve two lines (近鉄's B26 is both 京都線 and 橿原線 at 大和西大寺).
                if (code, e["link"]) in seen:
                    continue
                seen.add((code, e["link"]))
                line_id, svc_id = None, None
                svc = svc_by_title.get(core(e["link"])) if e["link"] else None
                if svc:
                    line_id, svc_id = service_line(svc, group_stations), svc["id"]
                if not line_id and e["link"]:
                    same = [x for x in group_stations if core(lines[x["line"]]["name"]["ja"]) == core(e["link"])]
                    if not same:
                        # An old or fuller name: 北近畿タンゴ鉄道宮津線 for our 宮津線.
                        same = [x for x in group_stations if len(core(lines[x["line"]]["name"]["ja"])) >= 2
                                and core(e["link"]).endswith(core(lines[x["line"]]["name"]["ja"]))]
                    if len({x["line"] for x in same}) == 1:
                        line_id = same[0]["line"]
                if not line_id and e["colour"]:
                    same = [x for x in group_stations if (lines[x["line"]].get("colour") or "").lower() == e["colour"]]
                    if len({x["line"] for x in same}) == 1:
                        line_id = same[0]["line"]
                if not line_id and e["link"]:
                    # Named with its operator: 富山地方鉄道本線, 山陽電気鉄道本線, 横浜市営地下鉄ブルーライン.
                    same = [x for x in group_stations if operator_of[x["line"]] and e["link"].startswith(operator_of[x["line"]])]
                    if len({x["line"] for x in same}) == 1:
                        line_id = same[0]["line"]
                if not line_id and len({x["line"] for x in group_stations}) == 1:
                    # Only one line of ours stops here: it can only be that one.
                    line_id = group_stations[0]["line"]
                number = {
                    "code": code, "prefix": e["prefix"], "number": e["number"],
                    # A number written out plainly has no colour of its own: its line's.
                    "colour": e["colour"] or (lines[line_id].get("colour") if line_id else None),
                    "shape": e["shape"], "line": line_id, "service": svc_id,
                }
                # On the station of its line; a number of no line of ours stays with the first station here.
                target = next((x for x in group_stations if x["line"] == line_id), None) or group_stations[0]
                target["numbers"].append(number)
                numbered += 1
                if not line_id:
                    report.append(f"station numbers: {code} at {title} ({e['link']}) matched no line")
    with_numbers = sum(1 for s in stations if s["numbers"])
    report.append(f"station numbers: {numbered} numbers on {with_numbers} of {len(stations)} stations")
    for s in stations:
        if not s["numbers"]:
            del s["numbers"]

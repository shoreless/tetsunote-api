"""Build the railway network shards in v0/ from 国土数値情報 N02 and data/operators.csv.

    uv run build/network.py

Each legal line (operator + registered line name) becomes a graph whose nodes are stations and
whose edges are segments: the track between two adjacent stations, with its length in km.
"""

import csv
import hashlib
import json
import re
import sys
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

import networkx as nx
import pykakasi
from pyproj import Geod, Transformer
from shapely import ops
from shapely.geometry import LineString, MultiLineString, Point

import borrow
import commons
import facts
import images as train_images
import places
import wikipedia
import series as rolling_stock
from names import LineNames, Names, ascii_name, line_slug_en

ROOT = Path(__file__).resolve().parent.parent
RELEASE = "N02-25"
SOURCE_URL = f"https://nlftp.mlit.go.jp/ksj/gml/data/N02/{RELEASE}/{RELEASE}_GML.zip"
SOURCE_DIR = ROOT / "sources" / "n02"
OUT = ROOT / "v0"

SNAP_M = 60  # a station belongs to a path if its platform is this close to the track
ABSORB_M = 1500  # a junction this close to a station along the track happens at that station
SIMPLIFY_M = 3
JOIN_M = 30  # track ends this close are the same point (N02 leaves small gaps between pieces)
BRIDGE_M = 1500  # a line still in pieces is joined across its nearest loose ends up to this far apart

ATTRIBUTION = (
    "「国土数値情報（鉄道データ）」（国土交通省）を加工して作成 / "
    "Processed from National Land Numerical Information (Railway), MLIT Japan, CC BY 4.0. "
    "English station names and readings from Wikidata, CC0"
)

geod = Geod(ellps="GRS80")
kakasi = pykakasi.kakasi()


def source_files():
    folder = SOURCE_DIR / f"{RELEASE}_GML" / "UTF-8"
    if not folder.exists():
        SOURCE_DIR.mkdir(parents=True, exist_ok=True)
        archive = SOURCE_DIR / f"{RELEASE}_GML.zip"
        print(f"Downloading {SOURCE_URL}")
        urllib.request.urlretrieve(SOURCE_URL, archive)
        zipfile.ZipFile(archive).extractall(SOURCE_DIR)
    return folder / f"{RELEASE}_RailroadSection.geojson", folder / f"{RELEASE}_Station.geojson"


def romaji_slug(text):
    words = "-".join(part["hepburn"] for part in kakasi.convert(text))
    for long, short in (("ou", "o"), ("oo", "o"), ("uu", "u")):
        words = words.replace(long, short)
    return re.sub(r"[^a-z0-9]+", "-", words.lower()).strip("-")


def line_slug(name):
    # "4号線丸ノ内線" → "丸ノ内", "中央線" → "中央"; the legal number adds nothing to an id
    core = re.sub(r"^\d+号線", "", name)
    core = re.sub(r"[（(].*?[)）]", "", core) or core
    core = re.sub(r"線$", "", core) or core
    return romaji_slug(core) or romaji_slug(name)


def load_operators():
    with open(ROOT / "data" / "operators.csv", encoding="utf-8") as f:
        return {row["n02"]: row for row in csv.DictReader(f)}


def utm_for(lon):
    zone = int((lon + 180) // 6) + 1  # JGD2011 / UTM zones 51–56 are EPSG:6688–6693
    epsg = 6688 + (zone - 51)
    return (
        Transformer.from_crs(6668, epsg, always_xy=True),
        Transformer.from_crs(epsg, 6668, always_xy=True),
    )


def transform(geom, t):
    return ops.transform(t.transform, geom)


def km(line_lonlat):
    return geod.geometry_length(line_lonlat) / 1000


def build_line(sections, stations, to_m, to_deg):
    """Return (graph, warnings). Graph nodes are station codes; edges carry metric geometry."""
    warnings = []
    merged = ops.linemerge(MultiLineString([transform(s, to_m) for s in sections]))
    paths = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]

    platforms = {code: transform(geom, to_m) for code, geom in stations.items()}
    g = nx.MultiGraph()
    snapped = set()
    for i, path in enumerate(paths):
        stops = []
        for code, platform in platforms.items():
            if path.distance(platform) <= SNAP_M:
                stops.append((path.project(platform.centroid), code))
        stops.sort()
        start, end = ("end", i, 0), ("end", i, 1)
        g.add_node(start, xy=path.coords[0])
        g.add_node(end, xy=path.coords[-1])
        cuts = [(0.0, start)] + stops + [(path.length, end)]
        for (a, na), (b, nb) in zip(cuts, cuts[1:]):
            if na == nb:
                continue
            piece = ops.substring(path, a, b)
            if piece.geom_type == "Point":  # a station sitting exactly on the path's end
                piece = LineString([piece.coords[0], piece.coords[0]])
            g.add_edge(na, nb, geom=piece, m=piece.length)
        snapped.update(code for _, code in stops)

    for code in platforms.keys() - snapped:
        warnings.append(f"station {code} is more than {SNAP_M} m from its line")
    g.add_nodes_from(snapped)

    # Path ends that touch each other are the same point: join them.
    ends = [n for n in g.nodes if isinstance(n, tuple)]
    for a in range(len(ends)):
        for b in range(a + 1, len(ends)):
            if ends[a] in g and ends[b] in g and Point(g.nodes[ends[a]]["xy"]).distance(Point(g.nodes[ends[b]]["xy"])) < JOIN_M:
                nx.contracted_nodes(g, ends[a], ends[b], self_loops=False, copy=False)

    # N02 sometimes leaves a real gap in a line, as on the Sekihoku Line near the closed Kanehana station,
    # where pieces miss each other by 600 m. Left alone, a station-less stretch there would be trimmed as
    # a dead end. Bridge the nearest loose ends of separate pieces, and say so in the report.
    while True:
        parts = list(nx.connected_components(g))
        if len(parts) < 2:
            break
        loose = [n for n in g.nodes if isinstance(n, tuple) and g.degree(n) == 1]
        best = None
        for i, part in enumerate(parts):
            for a in (n for n in loose if n in part):
                for b in (n for n in loose if n not in part):
                    d = Point(g.nodes[a]["xy"]).distance(Point(g.nodes[b]["xy"]))
                    if best is None or d < best[0]:
                        best = (d, a, b)
        if best is None or best[0] > BRIDGE_M:
            break
        d, a, b = best
        g.add_edge(a, b, geom=LineString([g.nodes[a]["xy"], g.nodes[b]["xy"]]), m=d)
        warnings.append(f"bridged a {d:.0f} m gap in the track at {to_deg.transform(*g.nodes[a]['xy'])}")

    changed = True
    while changed:
        changed = False
        # Up and down tracks drawn apart make parallel edges between the same two points: keep one.
        for u, v in set(g.edges()):
            keys = list(g[u][v]) if g.has_edge(u, v) else []
            if u == v:
                g.remove_edges_from([(u, v, k) for k in keys])
                changed = changed or bool(keys)
            elif len(keys) > 1:
                best = min(keys, key=lambda k: g[u][v][k]["m"])
                g.remove_edges_from([(u, v, k) for k in keys if k != best])
                changed = True
        for n in [n for n in g.nodes if isinstance(n, tuple)]:
            if n not in g:
                continue
            edges = list(g.edges(n, keys=True, data=True))
            if len(edges) == 0:
                g.remove_node(n)
                changed = True
            elif len(edges) == 1:  # dangling: siding or track past the last station
                g.remove_node(n)
                changed = True
            elif len(edges) == 2:
                (_, x, _, d1), (_, y, _, d2) = edges
                if x == y == n:
                    continue
                joined = ops.linemerge(MultiLineString([d1["geom"], d2["geom"]]))
                if joined.geom_type != "LineString":
                    joined = LineString(list(d1["geom"].coords) + list(d2["geom"].coords))
                g.remove_node(n)
                g.add_edge(x, y, geom=joined, m=d1["m"] + d2["m"])
                changed = True
            else:
                # A junction between stations: fold it into the nearest station along the track.
                near = min(
                    ((d["m"], other) for _, other, _, d in edges if isinstance(other, str)),
                    default=None,
                )
                if near and near[0] <= ABSORB_M:
                    nx.contracted_nodes(g, near[1], n, self_loops=False, copy=False)
                    changed = True

    junctions = sorted((n for n in g.nodes if isinstance(n, tuple)), key=str)
    for n in junctions:
        warnings.append(f"junction away from any station ({g.degree(n)} ways)")
    return g, warnings


def orient(geom, a_point):
    coords = list(geom.coords)
    if Point(coords[0]).distance(a_point) > Point(coords[-1]).distance(a_point):
        coords.reverse()
    return LineString(coords)


def routes_of(g):
    """Ordered station runs between line ends and branch points."""
    simple = nx.Graph(g)
    ends = [n for n in simple.nodes if simple.degree(n) != 2]
    seen, runs = set(), []
    for start in ends or list(simple.nodes)[:1]:
        for nxt in simple.neighbors(start):
            if frozenset((start, nxt)) in seen:
                continue
            run, prev, cur = [start], start, nxt
            seen.add(frozenset((start, nxt)))
            while True:
                run.append(cur)
                if cur in ends or cur == start:
                    break
                step = [x for x in simple.neighbors(cur) if x != prev]
                if not step:
                    break
                prev, cur = cur, step[0]
                seen.add(frozenset((prev, cur)))
            runs.append(run)
    return runs


def name_lines(shard, line_names, report):
    """Give each line its English name and colour, and an id made from the English name."""
    op = shard["operator"]
    found = {}
    for line in shard["lines"]:
        qids = {s["wikidata"] for s in shard["stations"].values() if s["line"] == line["id"] and s["wikidata"]}
        found[line["id"]] = line_names.match(op["legal_name"], line["name"]["ja"], qids)
    wanted = {}
    for old, f in found.items():
        wanted[old] = f["id"] or (f"{op['id']}.{line_slug_en(f['en'], op['name']['en'])}" if f["en"] else old)
    taken = defaultdict(list)
    for old, new in wanted.items():
        taken[new].append(old)
    rename = {}
    for old, new in wanted.items():
        rename[old] = new if len(taken[new]) == 1 else old  # two lines want one id: keep the legal-name ids
    for line in shard["lines"]:
        old, f = line["id"], found[line["id"]]
        new = rename[old]
        if not f["en"]:
            report.append(f"{old} ({op['legal_name']} {line['name']['ja']}): no English name")
        line["id"] = new
        line["name"]["en"] = f["en"]
        line["colour"] = f["colour"]
        line["wikidata"] = f["wikidata"]
        for seg in line["segments"]:
            seg["id"] = new + seg["id"][len(old):]
            for end in ("from", "to"):
                if seg[end].startswith(old + "#"):
                    seg[end] = new + seg[end][len(old):]
        for j in line["junctions"]:
            j["id"] = new + j["id"][len(old):]
        line["routes"] = [[new + n[len(old):] if n.startswith(old + "#") else n for n in r] for r in line["routes"]]
    for station in shard["stations"].values():
        station["line"] = rename[station["line"]]


def main():
    sections_path, stations_path = source_files()
    operators = load_operators()
    names = Names()
    line_names = LineNames()
    unnamed = 0
    sections = defaultdict(list)
    for f in json.load(open(sections_path, encoding="utf-8"))["features"]:
        p = f["properties"]
        sections[(p["N02_004"], p["N02_003"])].append(LineString(f["geometry"]["coordinates"]))

    station_parts = defaultdict(lambda: defaultdict(list))
    station_info = {}
    for f in json.load(open(stations_path, encoding="utf-8"))["features"]:
        p = f["properties"]
        key = (p["N02_004"], p["N02_003"])
        station_parts[key][p["N02_005c"]].append(LineString(f["geometry"]["coordinates"]))
        station_info[p["N02_005c"]] = {"name": p["N02_005"], "group": p["N02_005g"]}

    shards = defaultdict(lambda: {"lines": [], "stations": {}})
    report = []
    for (op_name, line_name), parts in sorted(sections.items()):
        op = operators.get(op_name)
        op_id = op["id"] if op else romaji_slug(op_name)
        line_id = f"{op_id}.{line_slug(line_name)}"
        # line_slug drops a leading 号線 number, so Nagoya's 2号線名城線 and 4号線名城線 would share an id:
        # a second line of the same slug takes its whole legal name, number included.
        if any(l["id"] == line_id for l in shards[op_id]["lines"]):
            line_id = f"{op_id}.{romaji_slug(line_name)}"
        stations = {c: ops.unary_union(geoms) for c, geoms in station_parts[(op_name, line_name)].items()}
        lon = MultiLineString(parts).centroid.x
        to_m, to_deg = utm_for(lon)
        g, warnings = build_line(parts, stations, to_m, to_deg)
        report += [f"{line_id} ({op_name} {line_name}): {w}" for w in warnings]
        junctions = sorted((n for n in g.nodes if isinstance(n, tuple)), key=str)
        g = nx.relabel_nodes(g, {n: f"{line_id}#j{i + 1}" for i, n in enumerate(junctions)})
        points = {c: transform(geom.centroid, to_m) for c, geom in stations.items()}
        points.update({n: Point(xy) for n, xy in g.nodes(data="xy") if xy})

        segments = []
        seen = set()
        for a, b, data in g.edges(data=True):
            if a == b:
                continue
            pair = tuple(sorted((a, b)))
            if pair in seen:
                continue
            seen.add(pair)
            a, b = pair
            geom = orient(data["geom"], points[a]).simplify(SIMPLIFY_M)
            lonlat = transform(geom, to_deg)
            segments.append({
                "id": f"{line_id}:{a}-{b}",
                "from": a,
                "to": b,
                "km": round(km(lonlat), 2),
                "geometry": [[round(x, 5), round(y, 5)] for x, y in lonlat.coords],
            })
        segments.sort(key=lambda s: s["id"])
        if not segments:
            # All of its track is drawn under another line (the Kaikyō Line under the Hokkaido Shinkansen).
            report.append(f"{line_id} ({op_name} {line_name}): no track of its own; left out")
            continue

        shard = shards[op_id]
        shard["operator"] = {
            "id": op_id,
            "name": {"en": op["en"] if op else None, "ja": op["ja"] if op else op_name},
            "legal_name": op_name,
        }
        line_stations = sorted(n for n in g.nodes if "#" not in n)
        shard["lines"].append({
            "id": line_id,
            "name": {"en": None, "ja": line_name},
            "colour": None,
            "km": round(sum(s["km"] for s in segments), 2),
            "km_source": "geometry",
            "routes": routes_of(g),
            "junctions": [
                {"id": j, "point": [round(c, 5) for c in to_deg.transform(*points[j].coords[0])]}
                for j in sorted(n for n in g.nodes if "#" in n)
            ],
            "segments": segments,
        })
        for code in line_stations:
            c = to_deg.transform(*transform(stations[code].centroid, to_m).coords[0])
            ja = station_info[code]["name"]
            found = names.match(code, ja, c)
            if not found["en"]:
                unnamed += 1
                report.append(f"{line_id} ({op_name} {line_name}): station {code} {ja} has no English name")
            shard["stations"][code] = {
                "id": code,
                "group": station_info[code]["group"],
                "line": line_id,
                "name": {"en": found["en"], "ja": ja},
                "ascii": ascii_name(found["en"]),
                "reading": found["reading"],
                "wikidata": found["wikidata"],
                "point": [round(c[0], 5), round(c[1], 5)],
            }

    # An operator whose only line had no track of its own has nothing to publish.
    for op_id in [k for k, v in shards.items() if not v["lines"]]:
        report.append(f"operator {op_id}: no lines with track of their own; left out")
        del shards[op_id]
    for shard in shards.values():
        name_lines(shard, line_names, report)
    borrow.apply(shards, report)

    line_ids = {line["id"] for shard in shards.values() for line in shard["lines"]}
    all_series, series_by_line, seat_classes = rolling_stock.load(line_ids, report)
    facts.build(all_series, report)
    articles = wikipedia.build(all_series, "series")
    all_lines = [line for shard in shards.values() for line in shard["lines"]]
    facts.build_lines(all_lines, report)
    line_articles = wikipedia.build(all_lines, "lines")
    photos = commons.photos(all_series, facts.entities(), train_images.listed(), report)
    pictures, line_pictures = train_images.build({s["id"] for s in all_series}, line_ids, report, photos)
    for record in all_series:
        record["image"] = pictures.get(record["id"])
    for shard in shards.values():
        for line in shard["lines"]:
            line["series"] = series_by_line.get(line["id"], [])
            for entry in line["series"]:
                if (entry["id"], line["id"]) in line_pictures:
                    entry["image"] = line_pictures[(entry["id"], line["id"])]
    listed = {(e["id"], line_id) for line_id, entries in series_by_line.items() for e in entries}
    for series_id, line_id in sorted(line_pictures.keys() - listed):
        report.append(f"data/train_images.csv: {series_id} has an image for {line_id} but is not listed on it")

    (OUT / "operators").mkdir(parents=True, exist_ok=True)
    listing = []
    for op_id, shard in sorted(shards.items()):
        body = {
            "version": 0,
            "languages": ["en", "ja"],
            "source": RELEASE,
            "attribution": ATTRIBUTION,
            "operator": shard["operator"],
            "lines": sorted(shard["lines"], key=lambda l: l["id"]),
            "stations": [shard["stations"][k] for k in sorted(shard["stations"])],
        }
        text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        path = f"operators/{op_id}.json"
        (OUT / path).write_text(text, encoding="utf-8")
        listing.append({
            "path": path,
            "operator": op_id,
            "name": shard["operator"]["name"],
            "lines": len(body["lines"]),
            "stations": len(body["stations"]),
            "bytes": len(text.encode()),
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        })

    published = {s["path"] for s in listing}
    for stale in (OUT / "operators").glob("*.json"):
        if f"operators/{stale.name}" not in published:
            stale.unlink()

    files = []
    series_text = json.dumps(
        {"version": 0, "languages": ["en", "ja"], "seat_classes": seat_classes, "series": all_series},
        ensure_ascii=False, separators=(",", ":"),
    )
    (OUT / "series.json").write_text(series_text, encoding="utf-8")
    files.append({
        "path": "series.json",
        "bytes": len(series_text.encode()),
        "sha256": hashlib.sha256(series_text.encode()).hexdigest(),
    })

    # Places for railway fans, with their photos and Wikipedia openings.
    all_stations = [st for shard in shards.values() for st in shard["stations"].values()]
    place_records = places.build(all_stations, report)
    facts.describe(place_records)
    place_articles = wikipedia.build(place_records, "places")
    place_photos = {row["id"]: row for row in commons.photos(place_records, facts.entities(), set(), report)}
    place_dir = OUT / "places"
    place_dir.mkdir(parents=True, exist_ok=True)
    keep = set()
    for record in place_records:
        row = place_photos.get(record["id"])
        record["image"] = None
        if row:
            image = train_images.Image.open(row["path"]).convert("RGB")
            full = train_images.resized(image, train_images.PHOTO_W)
            thumb = train_images.resized(image, train_images.THUMB_W)
            full.save(place_dir / f"{record['id']}.webp", "WEBP", quality=train_images.PHOTO_QUALITY, method=6)
            thumb.save(place_dir / f"{record['id']}-thumb.webp", "WEBP", quality=train_images.PHOTO_QUALITY, method=6)
            keep |= {f"{record['id']}.webp", f"{record['id']}-thumb.webp"}
            record["image"] = {
                "url": f"places/{record['id']}.webp", "thumb": f"places/{record['id']}-thumb.webp",
                "width": full.width, "height": full.height, "generated": False,
                "credit": row["credit"], "licence": row["licence"],
                "licence_url": row["licence_url"], "source_url": row["source_url"],
            }
    for stale in place_dir.glob("*.webp"):
        if stale.name not in keep:
            stale.unlink()
    places_doc = {"version": 0, "languages": ["en", "ja"], "places": place_records}

    for name, doc in (
        ("series_wikipedia.json", articles), ("lines_wikipedia.json", line_articles),
        ("places.json", places_doc), ("places_wikipedia.json", place_articles),
    ):
        doc_text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
        (OUT / name).write_text(doc_text, encoding="utf-8")
        files.append({
            "path": name,
            "bytes": len(doc_text.encode()),
            "sha256": hashlib.sha256(doc_text.encode()).hexdigest(),
        })

    for picture in sorted(train_images.OUT.glob("*.webp")) + sorted((OUT / "places").glob("*.webp")):
        data = picture.read_bytes()
        files.append({
            "path": f"{picture.parent.name}/{picture.name}",
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })

    hashes = [s["sha256"] for s in listing + files]
    revision = hashlib.sha256("".join(hashes).encode()).hexdigest()[:12]
    manifest = {
        "version": 0,
        "revision": revision,
        "languages": ["en", "ja"],
        "source": RELEASE,
        "attribution": ATTRIBUTION,
        "shards": listing,
        "files": files,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "build" / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    lines = sum(s["lines"] for s in listing)
    size = sum(s["bytes"] for s in listing)
    stations = sum(s["stations"] for s in listing)
    print(f"{len(listing)} operators, {lines} lines, {stations} stations ({unnamed} without English names), "
          f"{size / 1e6:.1f} MB; {len(report)} warnings in build/report.txt")


if __name__ == "__main__":
    sys.exit(main())

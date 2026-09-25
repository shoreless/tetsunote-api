"""Hand-entered track: data/track.geojson, for passenger track N02 does not have.

Each feature is a LineString from a station to add (`from_code`, an N02 station code, so the station
keeps its N02 name and group) to a station already on the line (`to`, by Japanese name). The
segment and station are added to that line, and the route is extended.
"""

import json
from pathlib import Path

from pyproj import Geod
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parent.parent
geod = Geod(ellps="GRS80")


def apply(shards, names, n02_stations, report):
    path = ROOT / "data" / "track.geojson"
    if not path.exists():
        return
    lines = {l["id"]: (shard, l) for shard in shards.values() for l in shard["lines"]}
    n02 = {f["properties"]["N02_005c"]: f for f in json.loads(n02_stations.read_text(encoding="utf-8"))["features"]}
    for n, feature in enumerate(json.loads(path.read_text(encoding="utf-8"))["features"], start=1):
        props = feature["properties"]
        where = f"data/track.geojson feature {n}"
        if props["line"] not in lines:
            raise SystemExit(f"{where}: unknown line {props['line']!r}")
        shard, line = lines[props["line"]]
        on_line = {x for seg in line["segments"] for x in (seg["from"], seg["to"])}
        to = next((s for s in shard["stations"].values() if s["id"] in on_line and s["name"]["ja"] == props["to"]), None)
        if not to:
            raise SystemExit(f"{where}: {props['to']} is not on {props['line']}")
        code = props["from_code"]
        if code not in n02:
            raise SystemExit(f"{where}: no N02 station {code}")
        record = n02[code]["properties"]
        coords = feature["geometry"]["coordinates"]
        point = [round(coords[0][0], 5), round(coords[0][1], 5)]
        if code not in shard["stations"]:
            found = names.match(code, record["N02_005"], point)
            shard["stations"][code] = {
                "id": code, "group": record["N02_005g"], "line": line["id"],
                "name": {"en": found["en"], "ja": record["N02_005"]},
                "reading": found["reading"], "wikidata": found["wikidata"], "point": point,
            }
        a, b = sorted((code, to["id"]))
        geometry = coords if a == code else coords[::-1]
        km = round(geod.geometry_length(LineString(coords)) / 1000, 2)
        line["segments"].append({
            "id": f"{line['id']}:{a}-{b}", "from": a, "to": b, "km": km,
            "geometry": [[round(x, 5), round(y, 5)] for x, y in geometry], "manual": True,
        })
        line["segments"].sort(key=lambda s: s["id"])
        line["km"] = round(line["km"] + km, 2)
        for route in line["routes"]:
            if route and route[0] == to["id"]:
                route.insert(0, code)
                break
            if route and route[-1] == to["id"]:
                route.append(code)
                break
        else:
            line["routes"].append([code, to["id"]])
        report.append(f"{line['id']}: added hand-entered track {record['N02_005']}–{props['to']} ({km} km)")

"""Track a line legally includes but N02 files under another line: data/line_borrow.csv.

Where two legal lines share track, N02 draws it once, under one of them. The Chūō Main Line starts at
Tokyo, but N02 puts the Tokyo–Kanda track under the Tōhoku Line only. Each row copies the segments
between two stations from the line that has them (`via`) onto the line that lacks them, and adds any
station that line had no record of, with an id of the other line's code plus `@` and this line's id.
"""

import csv
import heapq
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def path(line, a, b):
    """Segments along `line` from station a to station b, shortest first."""
    edges = {}
    for seg in line["segments"]:
        edges.setdefault(seg["from"], []).append(seg)
        edges.setdefault(seg["to"], []).append(seg)
    best, via, queue = {a: 0.0}, {}, [(0.0, a)]
    while queue:
        d, node = heapq.heappop(queue)
        if node == b:
            break
        for seg in edges.get(node, []):
            nxt = seg["to"] if seg["from"] == node else seg["from"]
            if d + seg["km"] < best.get(nxt, float("inf")):
                best[nxt], via[nxt] = d + seg["km"], seg
                heapq.heappush(queue, (d + seg["km"], nxt))
    if b not in via:
        return None
    out, node = [], b
    while node != a:
        seg = via[node]
        out.append(seg)
        node = seg["from"] if seg["to"] == node else seg["to"]
    return out[::-1]


def apply(shards, report):
    lines = {l["id"]: (shard, l) for shard in shards.values() for l in shard["lines"]}
    with open(ROOT / "data" / "line_borrow.csv", encoding="utf-8") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            where = f"data/line_borrow.csv line {n}"
            if row["line"] not in lines or row["via"] not in lines:
                raise SystemExit(f"{where}: unknown line {row['line']!r} or {row['via']!r}")
            shard, line = lines[row["line"]]
            via_shard, via = lines[row["via"]]

            def on(l, s, name):
                ids = {x for seg in l["segments"] for x in (seg["from"], seg["to"])}
                return next((st for st in s["stations"].values() if st["id"] in ids and st["name"]["ja"] == name), None)

            start, start_via = on(line, shard, row["from"]), on(via, via_shard, row["from"])
            end_via = on(via, via_shard, row["to"])
            if not (start and start_via and end_via):
                raise SystemExit(f"{where}: {row['from']} or {row['to']} is not on both lines")
            segments = path(via, start_via["id"], end_via["id"])
            if not segments:
                raise SystemExit(f"{where}: no track on {row['via']} from {row['from']} to {row['to']}")

            # Station ids on the borrowing line: its own where it has one, otherwise a new record.
            same = {start_via["id"]: start["id"]}
            for seg in segments:
                for code in (seg["from"], seg["to"]):
                    if code in same:
                        continue
                    theirs = via_shard["stations"][code]
                    mine = on(line, shard, theirs["name"]["ja"])
                    if mine:
                        same[code] = mine["id"]
                    else:
                        new_id = f"{code}@{line['id']}"
                        shard["stations"][new_id] = dict(theirs, id=new_id, line=line["id"])
                        same[code] = new_id
            added = 0
            for seg in segments:
                a, b = sorted((same[seg["from"]], same[seg["to"]]))
                seg_id = f"{line['id']}:{a}-{b}"
                if any(s["id"] == seg_id for s in line["segments"]):
                    continue
                geometry = seg["geometry"] if same[seg["from"]] == a else seg["geometry"][::-1]
                line["segments"].append({"id": seg_id, "from": a, "to": b, "km": seg["km"], "geometry": geometry, "borrowed": row["via"]})
                line["km"] = round(line["km"] + seg["km"], 2)
                added += 1
            line["segments"].sort(key=lambda s: s["id"])
            # Extend the route that ends at the joining station; otherwise start a new one.
            stops = [start["id"]]
            for seg in segments:
                nxt = same[seg["to"]] if same[seg["from"]] == stops[-1] else same[seg["from"]]
                stops.append(nxt)
            for route in line["routes"]:
                if route and route[-1] == start["id"]:
                    route.extend(stops[1:])
                    break
                if route and route[0] == start["id"]:
                    route[:0] = stops[:0:-1]
                    break
            else:
                line["routes"].append(stops)
            report.append(f"{row['line']}: borrowed {added} segment(s) {row['from']}–{row['to']} from {row['via']}")

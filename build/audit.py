"""Check the built network against Wikidata, to find track or stations N02 is missing.

    uv run build/audit.py

For each Wikidata line, adds up our lines matched to it (JR East's and JR Central's parts of the Chūō
Main Line together) and compares:
  - length: ours against Wikidata's; a large shortfall means missing track, as Tokyo–Kanda was;
  - termini: each end station Wikidata names should be a station on one of our lines.
Writes build/audit.txt. Differences can be real (Wikidata may describe a service, not the legal line),
so the list is for reading, not for fixing automatically.
"""

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LENGTH_TOLERANCE = 0.08  # and at least 2 km


def main():
    entities = json.loads((ROOT / "sources" / "wikidata" / "entities.json").read_text(encoding="utf-8"))
    lines, stations = [], {}
    for path in sorted((ROOT / "v0" / "operators").glob("*.json")):
        shard = json.loads(path.read_text(encoding="utf-8"))
        lines += shard["lines"]
        stations.update({s["id"]: s for s in shard["stations"]})

    # Termini are station items, often one per operator (a "Tokyo Station (JR East)" beside Tokyo
    # Station), so compare them to our stations by name rather than by Wikidata id.
    import re
    import sys
    sys.path.insert(0, str(ROOT / "build"))
    import facts
    ends_wanted = sorted({c["mainsnak"].get("datavalue", {}).get("value", {}).get("id")
                          for e in entities.values() for c in e.get("claims", {}).get("P559", [])} - {None})
    facts.fetch(ends_wanted, entities)

    def base(name):
        name = re.sub(r"[（(].*?[)）]", "", name or "").strip()
        return re.sub(r"(駅|停留場|停留所)$", "", name).translate(str.maketrans("ヶヵ", "ケカ"))

    by_item = defaultdict(list)
    for line in lines:
        if line.get("wikidata"):
            by_item[line["wikidata"]].append(line)

    def label(qid):
        e = entities.get(qid, {})
        return e.get("labels", {}).get("ja", {}).get("value") or e.get("labels", {}).get("en", {}).get("value") or qid

    short, long_, ends = [], [], []
    for qid, group in sorted(by_item.items(), key=lambda kv: kv[1][0]["id"]):
        entity = entities.get(qid, {})
        claims = entity.get("claims", {})
        ours = sum(l["km"] for l in group)
        ids = ", ".join(l["id"] for l in group)
        theirs = None
        for c in claims.get("P2043", []):
            v = c["mainsnak"].get("datavalue", {}).get("value", {})
            unit = v.get("unit", "").rsplit("/", 1)[-1]
            factor = {"Q828224": 1.0, "Q11573": 0.001}.get(unit)
            if factor:
                theirs = max(theirs or 0, float(v["amount"]) * factor)
        if theirs:
            gap = ours - theirs
            if abs(gap) > max(2.0, LENGTH_TOLERANCE * theirs):
                row = f"{label(qid)} ({ids}): ours {ours:.1f} km, Wikidata {theirs:.1f} km ({gap:+.1f})"
                (short if gap < 0 else long_).append((gap, row))
        ours_st = [stations[x] for l in group for seg in l["segments"] for x in (seg["from"], seg["to"]) if x in stations]
        on_ours = {base(st["name"]["ja"]) for st in ours_st} | {(st.get("ascii") or "").lower() for st in ours_st}
        for c in claims.get("P559", []):
            end = c["mainsnak"].get("datavalue", {}).get("value", {}).get("id")
            if not end:
                continue
            # Labels carry the operator ("JR東日本東京駅", "東急電鉄・東京メトロ渋谷駅"): match on how the name ends.
            name = base(label(end).replace("\u200e", "").strip())
            # One-character names (桂, 津) must match exactly; longer ones may follow an operator prefix.
            if not any(o and (name == o or name.lower() == o or (len(o) >= 2 and name.endswith(o))) for o in on_ours):
                ends.append(f"{label(qid)} ({ids}): terminus {label(end)} is not on our line")

    out = ["# Network audit against Wikidata", ""]
    out += [f"## Shorter than Wikidata ({len(short)}): possibly missing track", ""]
    out += [row for _, row in sorted(short)] + [""]
    out += [f"## Missing termini ({len(ends)})", ""] + ends + [""]
    out += [f"## Longer than Wikidata ({len(long_)}): usually branches or freight lines counted in ours", ""]
    out += [row for _, row in sorted(long_, reverse=True)] + [""]
    (ROOT / "build" / "audit.txt").write_text("\n".join(out), encoding="utf-8")
    print(f"{len(short)} shorter, {len(ends)} missing termini, {len(long_)} longer; see build/audit.txt")


if __name__ == "__main__":
    main()

"""Add official 営業キロ from MLIT regional transport bureau tables to data/official_km.csv.

    uv run build/official_import.py

Reads the bureau PDFs in sources/official/ (see SOURCES), pulls out each (line, section, km) entry,
and matches it to one of our lines by name, accepting the match only when both ends of the
section are stations on that line. Lines already in data/official_km.csv (from the operators' own
figures) are left as they are. Prints what it could not match, for a person to look at.
"""

import csv
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL = ROOT / "data" / "official_km.csv"
SOURCES = {
    "mlit-chubu-2-2-1-2.pdf": "https://wwwtb.mlit.go.jp/chubu/kousei/suuji/data/2-2-1-2.pdf",
}
BLOCK_SOURCES = {
    "mlit-shikoku-000321255.pdf": "https://wwwtb.mlit.go.jp/shikoku/content/000321255.pdf",
}
NUM = r"[\d.]+"


def entries(pdf):
    """(line, section, km) triples, in whichever of the table layouts the bureau uses."""
    raw = subprocess.run(["pdftotext", "-raw", str(pdf), "-"], capture_output=True, text=True).stdout
    raw = raw.translate(str.maketrans("（）～〜ｹﾉ", "()~~ケノ"))
    found = []
    # Chūbu: the line name, its section, then the km in brackets, each on its own line.
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    for a, b, c in zip(lines, lines[1:], lines[2:]):
        km = re.fullmatch(rf"\(({NUM})\)", c)
        if km and "~" in b and not re.search(r"\d", a):
            found.append((a.split()[-1], b, float(km[1])))
    # One entry on a line: "東日本旅客鉄道 伊東線 熱海~伊東(16.9)".
    for m in re.finditer(rf"(\S+線)\s+(\S+~\S+?)\(({NUM})\)", raw):
        found.append((m[1], m[2], float(m[3])))
    return found


def operator_blocks(pdf):
    """(operator, line, km) from tables listing an operator, its line names, then their km in order.

    Subtotals (計) are mixed into the km: a number equal to the sum since the last subtotal is one.
    """
    raw = subprocess.run(["pdftotext", "-raw", str(pdf), "-"], capture_output=True, text=True).stdout
    rows = [re.sub(r"\s+", "", l) for l in raw.splitlines() if l.strip()]
    out, i = [], 0
    while i < len(rows):
        if not rows[i].endswith("㈱"):
            i += 1
            continue
        operator = rows[i].removesuffix("㈱")
        i += 1
        names = []
        while i < len(rows) and rows[i] != "計" and not re.fullmatch(NUM, rows[i]):
            names.append(rows[i])
            i += 1
        while i < len(rows) and rows[i] == "計":
            i += 1
        numbers = []
        while i < len(rows) and re.fullmatch(NUM, rows[i]):
            numbers.append(float(rows[i]))
            i += 1
        k, acc = 0, 0.0
        for n in numbers:
            if acc and abs(acc - n) < 0.05:
                acc = 0.0  # a subtotal
                continue
            if k < len(names):
                out.append((operator, names[k], n))
                acc += n
                k += 1
    return out


def base(name):
    name = re.sub(r"^\d+号線", "", name)
    name = re.sub(r"[()（）].*", "", name)
    return re.sub(r"本線$", "線", name).replace(" ", "")


def station(name):
    return re.sub(r"(駅|停留場)$", "", name.replace("ケ", "ヶ")).replace("ヶ", "ケ")


def main():
    lines, stations, l_operator = [], {}, {}
    for path in sorted((ROOT / "v0" / "operators").glob("*.json")):
        shard = json.loads(path.read_text(encoding="utf-8"))
        lines += shard["lines"]
        l_operator.update({l["id"]: shard["operator"]["legal_name"] for l in shard["lines"]})
        stations.update({s["id"]: s for s in shard["stations"]})
    names_on = {
        l["id"]: {station(stations[x]["name"]["ja"]) for seg in l["segments"] for x in (seg["from"], seg["to"]) if x in stations}
        for l in lines
    }
    with open(OFFICIAL, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    have = {r["line"] for r in rows}
    added, unmatched = [], []
    for pdf, url in SOURCES.items():
        for name, section, km in entries(ROOT / "sources" / "official" / pdf):
            ends = [station(e) for e in section.split("~")] if section else []
            candidates = [l for l in lines if base(l["name"]["ja"]) == base(name)]
            # The section's ends must both be on the line; operator names in the tables are not needed.
            fits = [l for l in candidates if all(e in names_on[l["id"]] for e in ends)] if ends else candidates
            if len(fits) != 1:
                unmatched.append(f"{name} {section} {km} ({len(fits)} of {len(candidates)} candidates fit)")
                continue
            line = fits[0]
            if line["id"] in have:
                continue
            have.add(line["id"])
            rows.append({"line": line["id"], "official_km": km, "section": section.replace("~", "～"), "source": url, "checked": "2026-09-25"})
            added.append(f"{line['id']} {km}")
    for pdf, url in BLOCK_SOURCES.items():
        for operator, name, km in operator_blocks(ROOT / "sources" / "official" / pdf):
            fits = [l for l in lines if l_operator[l["id"]] == operator and base(l["name"]["ja"]) == base(name)]
            if len(fits) != 1:
                unmatched.append(f"{operator} {name} {km} ({len(fits)} fit)")
                continue
            line = fits[0]
            if line["id"] in have:
                continue
            have.add(line["id"])
            rows.append({"line": line["id"], "official_km": km, "section": "", "source": url, "checked": "2026-09-25"})
            added.append(f"{line['id']} {km}")
    with open(OFFICIAL, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["line", "official_km", "section", "source", "checked"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"added {len(added)}:", ", ".join(added))
    print(f"unmatched {len(unmatched)}:")
    for u in unmatched:
        print("  ", u)


if __name__ == "__main__":
    main()

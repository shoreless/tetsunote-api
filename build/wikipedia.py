"""The opening of each train model's Japanese and English Wikipedia article.

Wikipedia text is CC BY-SA 4.0, unlike the rest of this data, so it is published on its own in
v0/series_wikipedia.json with the licence and a link to each article, which is where its authors are
credited. Extracts are cached in sources/wikipedia/{lang}.json; delete a file to refresh it.
"""

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from facts import titles
from names import USER_AGENT

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "sources" / "wikipedia"
LICENCE = "CC BY-SA 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
# Enough to say what the train is and one thing about it; the app links to the rest.
WANT = {"ja": 160, "en": 320}
LIMIT = {"ja": 320, "en": 640}


def extract(lang, title):
    query = urllib.parse.urlencode({
        "action": "query", "prop": "extracts", "explaintext": 1, "exsectionformat": "plain",
        "exchars": 1200, "redirects": 1, "titles": title, "format": "json",
    })
    request = urllib.request.Request(
        f"https://{lang}.wikipedia.org/w/api.php?{query}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        pages = json.load(response)["query"]["pages"]
    return next(iter(pages.values())).get("extract", "")


def opening(raw, lang):
    """The first paragraphs, up to about WANT characters, cut at the end of a sentence."""
    end = "。" if lang == "ja" else ". "
    paragraphs = [p.strip() for p in raw.split("\n") if p.strip()]
    # Headings in plain format are short lines without sentence punctuation; skip them.
    paragraphs = [p for p in paragraphs if end.strip() in p or len(p) > 40]
    # Notes about the article itself ("本項では…表記する", "This article…") are not about the train.
    paragraphs = [p for p in paragraphs if not re.search(r"本項|本記事|本稿|表記する|記述する|This article", p)]
    text = ""
    for p in paragraphs:
        text = f"{text}\n\n{p}" if text else p
        if len(text) >= WANT[lang]:
            break
    text = re.sub(r"\s*\((?:[^()]*)\)" if lang == "en" else r"（(?:[^（）]*[ぁ-んァ-ン]+[^（）]*)）", "", text, count=1)
    if len(text) > LIMIT[lang]:
        cut = text.rfind(end.strip(), 0, LIMIT[lang])
        text = text[: cut + 1] if cut > 0 else text[: LIMIT[lang]] + "…"
    return text.strip()


def build(series):
    """Return the contents of v0/series_wikipedia.json."""
    CACHE.mkdir(parents=True, exist_ok=True)
    caches = {}
    for lang in ("ja", "en"):
        path = CACHE / f"{lang}.json"
        caches[lang] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    articles = {}
    for record in series:
        found = {}
        for lang, title in titles(record).items():
            cache = caches[lang]
            if title not in cache:
                cache[title] = extract(lang, title)
                time.sleep(0.2)
            text = opening(cache[title], lang)
            if text:
                found[lang] = {"title": title, "url": record["links"][f"wikipedia_{lang}"], "text": text}
        if found:
            articles[record["id"]] = found
    for lang, cache in caches.items():
        (CACHE / f"{lang}.json").write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return {
        "version": 0,
        "languages": ["en", "ja"],
        "licence": LICENCE,
        "licence_url": LICENCE_URL,
        "attribution": "Text from Wikipedia, the free encyclopedia; each entry links to its article, "
                       "whose history lists the authors. Shortened. / 出典: ウィキペディア（各記事の履歴に執筆者）。一部省略。",
        "series": articles,
    }

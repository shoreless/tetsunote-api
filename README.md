# tetsunote-api

Open data about Japan's railways, served as static JSON. It is the reference data behind the
鉄ノート (Tetsunote) railway logbook app.

There is no server: every endpoint is a file, served by GitHub Pages, so it is free to use and has
no rate limits or keys.

## Endpoints

Nothing is published yet. The first release will cover the Tokyo region.

| Path | What it holds |
| --- | --- |
| `v0/manifest.json` | Every shard with its hash and version, so apps download only what changed |
| `v0/operators/{id}.json` | One operator's lines, stations and segments (adjacent-station pieces of line with operating km and geometry). Lines also carry `facts` (opened, length, top speed, gauge, electrification), a `description` and `links` from Wikidata; these describe the Wikidata line, which can be a whole route where ours is a legal line |
| `v0/lines_wikipedia.json` | The opening of each line's Japanese and English Wikipedia article, shortened, under CC BY-SA 4.0 like `series_wikipedia.json` |
| `v0/series.json` | Train models (E235 series, N700S…) with operators, kind and status (active, retiring, retired). Where known: `facts` (entered service, retired, top speed, car length, number built, manufacturers), a one-line `description` and `links` from Wikidata, what it `replaces` and was `replaced_by`, and a short bilingual `about` of our own (marked `draft` until checked). Each line lists the models that run or ran on it in `series`, with a status for that line. A model with a picture has `image`: `url` and `thumb` (WebP, relative to `v0/`), size, `generated` (true for AI illustrations, which apps should label) and `credit`. A picture in the livery of particular lines is given only on those lines, as `image` on the model's entry in that line's `series`; prefer it over the model's own `image` |
| `v0/series_wikipedia.json` | The opening of each model's Japanese and English Wikipedia article, shortened. **Licensed CC BY-SA 4.0**, unlike the rest of this data; each entry links to its article. Apps showing it should credit Wikipedia and link the article |
| `v0/trains/*.webp` | Train pictures: our illustrations (1200 px), and for models without one, a photo from Wikimedia Commons (960 px), each with a `-thumb.webp` at 400 px. A photo's `image` has `credit` (the photographer), `licence`, `licence_url` and `source_url` (its Commons page); apps must show the credit and licence. Photos stay under their own licences. Every file is in the manifest with its hash |
| `v0/places.json` | Places for railway fans: museums, maglev and heritage railways, historic stations, and curated places such as train bars. Each has `kind`, `name`, `point` [lon, lat], its nearest `stations` (id and metres, within 3 km), `website`, a Wikidata `description` and `links`, and a Commons `image` with its credit |
| `v0/places_wikipedia.json` | The opening of each place's Wikipedia article, under CC BY-SA 4.0 |
| `v0/services.json` | Services (運転系統): the trains riders board, where they differ from the legal lines, such as 中央線快速 and 中央・総武線各駅停車 on the one 中央線, or 湘南新宿ライン over three lines, and the shinkansen that run through from one line to the next. Each has `name`, `kind`, `colour`, `trains` (the train names, for shinkansen), `series` (the train models of a service that has its own, like スペーシアX) and `sections`: a `line` with the `segments` it runs over and the stations it `stops` at. `through` lists where one line's trains run on into another (東西線 into 中央線 at 中野), with the station on each |
| `v0/events.json` | Depot open days, festivals, farewell runs and stamp rallies, with `starts` and `ends` |

Every text field a reader might see is given in both languages as `{"en": "…", "ja": "…"}`.
Station English names use Hepburn with macrons (Ōtemachi); each station also carries `ascii`
(Otemachi), as most station signs show it and people type it, and a kana `reading` (おおてまち).
Every record has a stable id, names its `source`, and carries a `checked` date: when someone last
confirmed it.

## Layout

| Folder | What it holds |
| --- | --- |
| `sources/` | Raw downloads such as 国土数値情報. Not committed; the build fetches them |
| `data/` | Curated records: places, events, eki stamps, tetsuin railways, train models, and train pictures in `data/trains/` (listed in `data/train_images.csv`). Edited by pull request |
| `build/` | Scripts that turn `sources/` and `data/` into `v0/` |
| `v0/` | The published output. Never edited by hand |

## Building

### Interactive atlas

`index.html` is the public landing page: a Three.js railway atlas that reads the same `v0/`
files as API clients. It includes nationwide and regional views, operator search, line selection,
station inspection, and 2D/3D map controls. Drag to pan, scroll to zoom, and right-drag to tilt.
On touch screens, drag with one finger and pinch/rotate with two.

Preview the repository over HTTP (opening the HTML directly will not work):

```
python3 -m http.server 8080 --bind 127.0.0.1
```

Visit `http://localhost:8080`. GitHub Pages can serve the repository root directly, including
`index.html`, `assets/`, `.nojekyll`, and `v0/`; no frontend build is required. All asset and API
paths are relative, so project Pages URLs work too. Three.js is vendored locally. To update those
files after changing the pinned dependency, run `npm ci` and `npm run vendor`.

The atlas loads the manifest and operator shards with at most eight concurrent requests.
Line colors use the API’s `colour` field where available, with stable fallback colors for other lines. Kilometers are geometry
estimates, station counts are source records (not unique physical stations), and registered
lines may differ from passenger service names. Coastline and dependency attribution is in
`assets/NOTICE.md`.

### Railway data

```
uv run build/network.py
```

This downloads 国土数値情報 N02 into `sources/` if it is missing, then writes `v0/operators/` and
`v0/manifest.json`. Anything the build could not resolve, such as a junction away from any
station, is listed in `build/report.txt`.

## Checking the network

N02 draws shared track once, under one line, and sometimes leaves gaps. Two things keep the network
honest:

- `data/line_borrow.csv` gives a line track it legally includes but N02 files under another line.
  The Chūō Main Line borrows Kanda–Tokyo from the Tōhoku Line this way.
- `data/services.csv` and `data/service_sections.csv` describe each service as sections along legal
  lines through waypoint stations, so it follows the branch its trains use; the build fails if a
  section doesn't follow its line. The stops are the stations on those sections that the service's
  Japanese Wikipedia station table (駅一覧) lists as served (facts only), unless a section lists them
  or says `all`. `data/through.csv` gives the through-running between lines.
- `data/official_km.csv` holds the operators' published 営業キロ for each line, with the source:
  JR Hokkaido, JR Central, JR West and JR Kyushu from their own figures, and the lines listed by the
  MLIT Chūbu and Shikoku transport bureaus (every operator in those regions). `uv run
  build/official_import.py` reads the bureau tables in `sources/official/` and adds a line only when
  both ends of its section are stations on it.
  Lines carry it as `official_km`. Our `km` is measured from N02's geometry; `official_km` is what
  fares and noritsubushi count by (for shinkansen it follows the parallel conventional line).
- `data/track.geojson` holds passenger track N02 lacks, drawn by hand: the link that takes Sangi Line
  trains to Kintetsu-Tomida.
- `uv run build/audit.py` compares every line with Wikidata (our length against Wikidata's, and each
  terminus Wikidata names against our stations) and with the official 営業キロ. It writes `build/audit.txt`. Most differences are
  expected (closed sections, a service drawn where we keep the legal line, planned extensions), so
  the list is read, not applied.

The build itself also joins track pieces up to 1.5 km apart when a line would otherwise be split,
and lists each join in `build/report.txt`.

## Adding a place

Places come from Wikidata where it has them. To add one it lacks, such as a train bar or a photo
spot, add a row to `data/places.csv` with `kind` (museum, maglev, heritage-railway, railway-park,
historic-station, bar, cafe, shop, viewpoint, other), `ja`, `en`, `lat`, `lon`, `website`, `source`
and the date you `checked` it. To hide a Wikidata place (closed, not open to the public), give its
`wikidata` id and `hide` = yes, with a `note` saying why.

## Corrections and submissions

Open an issue or a pull request against `data/`. Nothing is published until it has been reviewed.

## Versioning

**`v0` is not yet stable.** Fields may change while the app that uses it settles. When the format is
stable it will be published as `v1`, and from then on a breaking change means a new version path, not
an edit to an existing one.

## Please check the source

This is a convenience, not an authority. Events move and places close. Where it matters, check the
source each entry names.

## Attribution

Train facts and descriptions come from [Wikidata](https://www.wikidata.org/) (CC0). Train photos come from
[Wikimedia Commons](https://commons.wikimedia.org/), only where freely licensed; each names its author,
licence and file page. The text in
`v0/series_wikipedia.json` is from Wikipedia and stays under CC BY-SA 4.0.

Each source will be credited here, with a note where its data has been processed. Licence terms for
国土数値情報, ekidata.jp and ODPT are being confirmed before anything derived from them is published.

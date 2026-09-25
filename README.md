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
| `v0/operators/{id}.json` | One operator's lines, stations and segments (adjacent-station pieces of line with operating km and geometry) |
| `v0/series.json` | Train models (E235 series, N700S…) with operators, kind and status (active, retiring, retired). Each line lists the models that run or ran on it in `series`, with a status for that line |
| `v0/places.json` | Museums, notable stations, viewpoints, preserved locomotives and 廃線跡 |
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
| `data/` | Curated records: places, events, eki stamps, tetsuin railways. Edited by pull request |
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

Each source will be credited here, with a note where its data has been processed. Licence terms for
国土数値情報, ekidata.jp and ODPT are being confirmed before anything derived from them is published.

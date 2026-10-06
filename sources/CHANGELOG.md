# Shared scraper files - changelog
Identical in AutoPack Builder and Autoedgeware: `sources/*.py`, `core/netlog.py`, `thumbs.py`, `query_clean.py`,
`media_item.py`, `winproc.py`. Check a copy with `python tools/sources_sync.py`.

## 2026.10.05.2
- New sites: e621, Danbooru, Yande.re, Konachan, Derpibooru (JSON APIs, via the new shared `sources/json_board.py`), Wallhaven, Civitai, Lemmy. Each has its own Sort choices (see below); `Source.suggest(query)` is an optional pick-list helper (Reddit, Danbooru, e621, Derpibooru, Moebooru, Civitai, Lemmy implement it).
- `core/safety.py` (new shared file): a built-in guard that always skips posts and searches pointing to minors. Used by the booru family, the JSON boards and (in the app) the engine for every site. The booru website-page path now reads each thumbnail's alt/title text so the guard works there too.
- Sort: e621/Danbooru/Derpibooru/Yande.re/Konachan = Highest score, Newest (+ Random on e621, Danbooru, Derpibooru) with a Min score; Wallhaven = Best match, Hot, Most favorited, Most viewed, Top week/month/year, Newest, Random; Civitai = Most reactions week/month/year/all time, Most comments, Newest; Lemmy = Hot, New, Top day..all time.

## 2026.09.30.5
- **Interface change:** per-site Sort choices replace Quality. New class attrs `order_choices`, `default_order`, `min_score_choices`, `order_help` (choices are `(key, label, params)`, params from `sort`/`time_range`/`query_suffix`) and `Source.resolve(order, min_score)`. Removed `supports_quality`, `resolve_quality`, `has_sort`, `has_time`, `sort_options`, `time_options`, `default_sort`, `quality_scores`. `fetch()` is unchanged.
- Reddit: Hot now (default), New, Rising, Top today/week/month/year/all. Redgifs: Best match (default), Trending, Latest, Top week/month/all. Freesound: Relevance, Most downloaded, Highest rated, Newest. Erome: Hot, New.
- Boorus: Sort = Highest score (`sort:score`, default) / Newest / Random (Gelbooru only); Min score Any, 5, 10, 25, 50, 100 (`score:>=N`).

## 2026.09.30.4
- Comments and docstrings trimmed (no behavior change); real page dumps in tests replaced by synthetic pages.

## 2026.09.30.3
- Redgifs: search by official tag (`tags=Hypno&type=g`); `search_text=` is ignored by the API. Words resolve via `/v2/search/suggest`; results are checked against the tag.

## 2026.09.30.2
- `core/winproc.py`: `quiet()` on every subprocess call, so no console windows flash on Windows.
- Redgifs: image posts saved as images, photo-loop videos become JPEGs (ffmpeg), Prioritize favours videos.
- `MediaItem.extra` feeds the run log.

## 2026.09.30.1
- Redgifs sort orders are the API's own (default `score`); `new` returned HTTP 400.
- Booru `api_policy`: Gelbooru/Rule34 use the API only with key + user ID, RealBooru never; HypnoHub = API then website pages.
- File-URL regex host part tightened; Soundgasm random by default.

## 2026.09.29 (baseline)
- Booru refusals (XML, JSON message, bare string, HTML) fall back to the website pages; netlog retries and redacts; error pages discarded; Redgifs token refresh; `skip_ids` and `item_cb` everywhere.

# Changelog

## v0.1.7
- Hentai Foundry: Settings now has **Open browser to sign in** / **Save session**. It opens the site in a Chrome/Edge
  window with its own profile folder (your everyday browser profile is not read); you pass the bot check yourself, then
  the program reads that window's cookies and user-agent through the browser's local debugging channel
  (`core/browser_session.py`, `core/miniws.py`) and sends the same ones. Nothing is solved or faked. Pasting a cookie by
  hand still works.

## v0.1.6
- Find now also covers Sex.com (Pics, GIFs; with the site's result count), Wallhaven (count), Erome and Soundgasm
  (creator name; upload count). Each lookup loads the first results page to confirm something matches; a site that can't
  be reached is still listed, just without a number. These entries are exempt from "Hide small".

## v0.1.5
- Download progress is now plain text on the bottom line (no second bar, nothing moves). **Skip file** is red and
  active while a run is going, greyed out otherwise; it also works while a file is still waiting for the server.
- New sites: **Sex.com Pics**, **Sex.com GIFs** (first page from the page's own data, later pages from its search API;
  Most popular / Newest) and **Hentai Foundry** (search grid, then each picture's page for the full-size file).
  Hentai Foundry blocks scripts with a bot check; the program does not work around it. Paste the Cookie header from your
  own browser under Settings > Hentai Foundry cookie.

## v0.1.4
- Big downloads: live bar (`12.3 MB of 75 MB - 1.4 MB/s`) and a **Skip file** button. **Stop** now cuts a download
  within about a second. New Settings option: skip files over N MB (checked from the size header, before downloading).
- Duplicates: a new file byte-identical to any file already in the collection (from any site) is removed, and content you
  delete with the X is never fetched again from another site. Existing files are hashed once and cached.
- No console window: `run.bat` starts `collector.pyw` (errors go to `collector_crash.log`).
- HTTP call logging and transient-error retries are now actually switched on in the app (they were only on in tests).
- Reddit wait note reads "Reddit rate limiting - waiting Ns".

## v0.1.3
- Find now covers the booru family (Gelbooru, Realbooru, Hypnohub, Rule34, Safebooru, TBIB, Xbooru): tag lookups with
  post counts, trying each engine's known autocomplete route.
- Red flashing dot in the footer while Reddit's rate limit makes the program wait ("not a program fault").

## v0.1.2
- **Check all sites** button: one tiny search per site, results window with status, timing and HTTP details.
- Version number shown in the title bar, Log header and README.
- Add box adapts per site: Sort choices, Min score (boorus), Random, Prioritize, default Limit, query hint,
  pasted-URL cleanup. Limit and Type live beside it; no Apply step.
- Searches to run: Status symbols plus Site, Query, Sort, Limit, Options columns; Edit, Re-run, context menu.
- Find: exact subreddit names are checked directly (about.json, then RSS) and shown first; sites that return nothing
  are named in the status line and the Log.
- Shared scraper layer updated to AutoPack Builder v0.1.29 (sources 2026.10.05.2): per-site Sort replaces Quality.
  Only difference: the user-agent says MediaCollector, and Civitai stays off.

## v0.1.1 and earlier
- Three-column layout, popularity-ranked Find, Log tab with export, always-visible Start/Stop, per-search settings.

# Changelog

## v0.1.11
- **Interface refresh:** the three columns are now separate cards with gaps between them; flatter buttons, slimmer scrollbars, roomier tables and fields. Same colours.
- Folder layout: `run.bat`, `collections/` and `app/` (program, tests, tools). Removed unused code (Civitai source, helpers, imports) and trimmed comments.
- New collection: themed name dialog. Stale `collections` path from a copied app now falls back to this app's own folder.
- **Site list has headings:** Image boards / Video / Image & mixed / Audio. Find > Match rows for PMV Haven and HypnoTube now start with the site name.
- **Two new video sites (category "Videos"):**
  - **PMV Haven** - uses the site's own JSON API. Search words, `tag:Trans`, `creator:Infinite`, or empty for everything.
    Pick-list shows how many videos each keyword / tag / creator has. Order: newest, most viewed, best rated, most liked
    (tag / creator / empty lists). Quality: 720p+, 1080p+, 70%+ / 85%+ rating. Downloads the original MP4.
  - **HypnoTube** - keyword search or `channel:11/hypnosis` (pick-list lists the site's channels with counts). Order: best match,
    newest, top rated, most viewed. Quality: HD only, 70%+ / 85%+ liked. The site rate-limits searches, so these run slowly (about 3 s per page).
- **New** button beside Collection: asks "Name your new collection." and opens it empty.
- **Sites run side by side.** Different sites are searched at the same time (Settings > "Sites at once", default 3,
  1 = one at a time), so a rate-limited Reddit no longer holds up the rest. One site's own searches still run in
  order, which keeps its rate limit. Skip file / Skip source act on every search running at that moment.
- **Reddit first-frame images fixed for good:** the post thumbnail is now used only for image posts. Video links
  (redgifs, streamable, YouTube, direct mp4...) and external pages never fall back to it, even when the video
  can't be fetched. Direct .mp4/.webm links are now downloaded as video.
- Fixed a race when several searches finished together and saved the collection at once.
- Each search stages its downloads privately; keep/duplicate decisions are made one at a time, so two sites can't
  both keep the same file.

## v0.1.10
- **Files are prefixed with their site:** `xyz.jpg` -> `reddit_xyz.jpg`.
- **Same search can be queued twice** with different Order / Min score (e.g. Reddit New and Top This Month).
- **Skip source** button beside Skip file: abandons the running search, keeps what it found, moves on.
- **Reddit:** the 6.5 s pacing now applies only to reddit.com requests (not video/image hosts); video posts no
  longer fall back to the thumbnail (a first-frame jpeg).
- **One folder per collection.** Every site and search now saves into the collection's own folder instead of a
  sub-folder per site/search. Same-named files never overwrite each other, and duplicates across sites are caught
  as before. Existing sub-folders stay and are still checked for duplicates.
- **Site check fixes (found on a real PC):** Gelbooru/RealBooru/Safebooru-style sites no longer download whole videos
  during a check (they take an image or probe the file); Reddit's check no longer times out on its request pacing;
  Hentai Foundry's stalled request now shows the Connect browser hint.
- Booru file names no longer contain HTML codes like `&#039;` or `&gt;`.
- **Hentai Foundry Connect browser fixed:** the cookies were captured but dropped because of a domain mismatch
  (`www.` vs bare host). The browser flow also now waits until a real request with the captured cookies returns search
  results, so click the site's *Enter* button and it finishes by itself. The status line shows the page the app sees.
- Removed the old `collector.py` (use `collector.pyw` or `run.bat`).
- **Find**
  - Coomer / Kemono also search the site's own posts: creators whose posts mention your word are listed.
  - Erome and Fapello show album / post counts (a trailing "+" means more pages exist); an unknown Fapello model is not listed.
  - Freesound shows its result count (needs the API key from Settings); Hentai Foundry confirms the word once Connect browser is done.
  - Yande.re / Konachan tag lookup now matches the word as a substring instead of returning the most popular tags.
- **Coomer / Kemono:** the full-size attempt is capped at 12 s, so the preview fallback starts sooner (was ~53 s).
- **Large files:** Settings > *Skip files over (MB)* (e.g. 25) skips big videos instantly.

## v0.1.9
- **Hentai Foundry: Connect browser.** Settings > Hentai Foundry cookie > *Connect browser* opens your installed Chrome or
  Edge; pass the bot check yourself and the session's cookies and User-Agent are saved and reused (the User-Agent must
  match or the cookie is rejected). No extra packages; PCs without Chrome/Edge get an *Install browser component* button.
  Pasting a Cookie header by hand still works.
- **Coomer / Kemono**
  - When the full-size file servers can't be reached (blocked network), images fall back to the site's preview images
    (saved as `..._preview.jpg`); videos fail fast with a clear log line instead of waiting minutes each.
  - A bare Coomer username is looked up on OnlyFans, Fansly and CandFans; display names also match the creator list
    ("Queenofmilk" = "Queen Of Milk"). Fansly creators are addressed by number: paste the page link or `fansly/user/ID`.
  - New optional Settings fields *Kemono address* / *Coomer address* for when the sites move to a mirror domain.
  - API and file requests honor Stop within a second and give up after 40 s / 90 s; the log shows each step.
- Only the media types you tick are downloaded (sources that can skip unwanted types before downloading now do).
- **Site check:** image results are really downloaded (up to 30 MB) so the results window shows them; videos stay
  placeholders. A timed-out site keeps its HTTP calls and log lines in the report; sites with no result show their last
  three log lines. Kemono/Coomer get a longer per-site limit. Probes read 64 KB, not 10 MB.
- New tools: `tools/site_check.py` (site check without the window, writes `site_check_report.txt`) and
  `tools/probe_media.py` (why can't this file be fetched? tests IPv4/IPv6 and header sets).

## v0.1.8
- Site checks probe up to 10 MiB of media instead of 1 KiB.
- Site checks now have a bounded overall timeout and cannot hang the entire 25-site test indefinitely.
- Fixed false "fail" results for sources whose site-check item was returned but not sent through `item_cb`.
- Site-check response reads now have an 8-second idle limit and honor the per-site timeout event.
- Kemono/Coomer API responses now transparently decode gzip/deflate content.
- Coomer/Kemono and other site-check probes stop promptly when their per-site timeout is reached.

## v0.1.7
- Site checks now use bounded media probes instead of full media downloads where supported.
- Site-check HTTP calls are capped and do not retry transient media failures, preventing multi-minute hangs.
- Coomer/Kemono stop walking every attachment after a failed site-check media probe.
- Coomer Find -> Match can offer a bare username without the creators endpoint.
- Kemono non-JSON API replies now include a useful response snippet.
- Lemmy accepts thumbnail-backed media posts when URL metadata is incomplete.
- Fapello/Erome site checks probe media without downloading the full file.

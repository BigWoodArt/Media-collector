# Media Collector

Type a topic, tick the matches, press Start. The program asks each supported site for its own real
subreddits, tags, communities and creators, downloads what you chose into a themed folder, and shows
a live preview where one click rejects anything you don't want.

> **Notices.** Several supported sites host adult material: **18+ only**. Unofficial, personal-use tool,
> not affiliated with any site. You are responsible for each site's rules and your local laws.

## Quick start
1. Install **Python 3.9+** with Tk (Windows/macOS installers include it; Debian/Ubuntu: `sudo apt install python3-tk`).
2. `python -m pip install -r requirements.txt` (only Pillow, for previews), then `python collector.py`
   (Windows: double-click `run.bat`).
3. Type a topic, press **Find**, tick matches, press **Start**.

## Using it
- **Collection** = a themed folder. It remembers what it has fetched, so running again only adds new items.
- **Matches** come from the sites themselves (never guessed). Sites with no search (e.g. Soundgasm creators)
  use **Add by name**.
- **Quality** Any / Good / Best is translated per site (minimum score, top of month/year, ...).
- **Click a picture** to reject it, then **Remove rejected**: the file is deleted and never fetched again.
- **Export ZIP** packs a collection. **Advanced** picks a site's own sort/time.

## Sites
Reddit, Redgifs, Soundgasm, Freesound, Erome, Gelbooru, Realbooru, Hypnohub, Rule34, Safebooru, TBIB, Xbooru,
e621, Danbooru, Yande.re, Konachan, Derpibooru, Wallhaven, Civitai (civitai.red, API key required), Lemmy.
Optional accounts/keys go in **Settings** and are stored only in `collector_settings.json` beside the program.

## Trust and transparency
- **AI-assisted.** This code was written with Claude. Read it: no minified code, no build step, standard library
  plus Pillow only.
- **Network.** No telemetry, no analytics. The only connections go to the sites you pick, paced to their limits.
  `core/netlog.py` records each request (secrets redacted) so you can verify.
- **Tests.** `python -m unittest discover tests` runs offline against simulated replies; CI runs it on every push.
- **Content guard.** `core/safety.py` skips any post or search involving minors. It is intentionally not configurable.
- **No bypassing.** Logins, paywalls and access controls are respected; when a site blocks plain requests the
  tool says so instead of working around it.

## Developing a new site
Subclass `JsonBoardSource` (JSON APIs) or `Source`, implement `fetch()` and optionally `suggest()`,
add it to `sources/__init__.py`, and add an offline test beside `tests/test_new_sources.py`.

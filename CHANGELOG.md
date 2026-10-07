# Changelog

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

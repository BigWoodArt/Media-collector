# Changelog

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

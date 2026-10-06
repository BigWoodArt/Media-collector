"""Pasted-URL cleanup: reduce a site URL to the bare subreddit / tag / creator."""
import re
import urllib.parse

URL_CLEANUP = {
    "reddit": re.compile(r'^https?://(?:www\.|old\.|new\.)?reddit\.com/r/', re.I),
    "redgifs": re.compile(r'^https?://(?:www\.)?redgifs\.com/(?:watch|tags|gifs)/', re.I),
    "soundgasm": re.compile(r'^https?://(?:www\.|media\.)?soundgasm\.net/u/', re.I),
    "freesound": re.compile(r'^https?://(?:www\.)?freesound\.org/(?:browse/tags|search)/', re.I),
    "erome": re.compile(r'^https?://(?:www\.)?erome\.com/search\?q=', re.I),
    "gelbooru": re.compile(r'^https?://(?:www\.)?gelbooru\.com/index\.php\?.*[?&]tags=', re.I),
    "realbooru": re.compile(r'^https?://(?:www\.)?realbooru\.com/index\.php\?.*[?&]tags=', re.I),
    "hypnohub": re.compile(r'^https?://(?:www\.)?hypnohub\.net/post(?:/index)?(?:\.json)?\?.*[?&]tags=', re.I),
}
TAG_STYLE = {"gelbooru", "realbooru", "hypnohub", "erome"}


def clean_query(site_id: str, text: str) -> str:
    text = (text or "").strip()
    pattern = URL_CLEANUP.get(site_id)
    if not pattern:
        return text
    after = pattern.sub("", text)
    if after == text:
        return text
    if site_id in TAG_STYLE:
        return urllib.parse.unquote_plus(after.split("&")[0]).strip()
    return after.split("/")[0].split("?")[0].strip()

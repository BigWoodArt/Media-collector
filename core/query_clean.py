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
    "danbooru": re.compile(r'^https?://danbooru\.donmai\.us/posts\?.*[?&]tags=', re.I),
    "e621": re.compile(r'^https?://e621\.net/posts\?.*[?&]tags=', re.I),
    "yandere": re.compile(r'^https?://yande\.re/post\?.*[?&]tags=', re.I),
    "konachan": re.compile(r'^https?://konachan\.(?:com|net)/post\?.*[?&]tags=', re.I),
    "derpibooru": re.compile(r'^https?://(?:www\.)?derpibooru\.org/search\?.*[?&]q=', re.I),
    "sexcom_pics": re.compile(r'^https?://(?:www\.)?sex\.com/[a-z]{2}/pics\?(?:.*&)?search=', re.I),
    "sexcom_gifs": re.compile(r'^https?://(?:www\.)?sex\.com/[a-z]{2}/gifs\?(?:.*&)?search=', re.I),
    "hentaifoundry": re.compile(r'^https?://(?:www\.)?hentai-foundry\.com/search/index\?(?:.*&)?query=', re.I),
    "wallhaven": re.compile(r'^https?://wallhaven\.cc/search\?.*[?&]q=', re.I),
}
TAG_STYLE = {"gelbooru", "realbooru", "hypnohub", "erome", "danbooru", "e621", "yandere", "konachan",
             "derpibooru", "wallhaven", "sexcom_pics", "sexcom_gifs", "hentaifoundry"}


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

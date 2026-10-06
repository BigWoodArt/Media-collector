"""Hentai Foundry search.
The site shows a "making sure you're not a bot" page to scripts. This source does NOT try to get around it: in
Settings you open the site in a real browser window, pass the check yourself, and the program reuses that session's
cookies (see core/browser_session.py). It expires, so repeat when searches stop working. Requests are slow (about 2.5 s apart)."""
import html
import re
import urllib.error
import urllib.parse

from sources.json_board import JsonBoardSource, ApiError

BASE = "https://www.hentai-foundry.com"
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
BLOCK_HELP = ("Hentai Foundry's bot check stopped this request. In Settings, use 'Open browser to sign in', pass the "
              "check in that window, then 'Save session' (it expires, so repeat when it stops working). "
              "Or paste your browser's Cookie header there by hand.")
BLOCK_RE = re.compile(r"<div class=['\"]thumb_square['\"]>(.*?)(?=<div class=['\"]thumb_square['\"]>|<div class=['\"]pagebar|$)", re.S)
LINK_RE = re.compile(r'class="thumbLink" href="(/pictures/user/([^/"]+)/(\d+)[^"]*)"')
TITLE_RE = re.compile(r'<span title="([^"]*)" class="thumb"')
RATING_RE = re.compile(r"class='rating[^']*' title='([^']*)'")


def parse_results(page):
    """-> (posts, has_next)."""
    posts = []
    for block in BLOCK_RE.findall(page):
        m = LINK_RE.search(block)
        if not m:
            continue
        t = TITLE_RE.search(block)
        title = html.unescape(t.group(1)) if t else ""
        posts.append({"id": m.group(3), "url": "pending:" + m.group(1), "path": m.group(1), "user": m.group(2),
                      "tags": [], "title": title,
                      "text": " ".join([title, m.group(2)] + RATING_RE.findall(block))})
    has_next = bool(re.search(r'<li class="next"><a', page))
    return posts, has_next


class HentaiFoundrySource(JsonBoardSource):
    id, label = "hentaifoundry", "Hentai Foundry"
    category = "Art sites"
    prefix = "hf_"
    base_url = BASE
    check_query = "cat"
    query_hint = "search word (e.g. cat)"
    default_limit = 20
    min_interval = 2.5
    has_media_priority = False
    order_choices = []
    default_order = ""
    min_score_choices = []
    order_help = "Results are in the site's own search order."

    def __init__(self, cookie="", user_agent=""):
        super().__init__()
        self.cookie = cookie.strip()
        self.ua = user_agent.strip()      # the browser that passed the check; its pass is tied to that identity

    def _headers(self):
        h = dict(BROWSER_HEADERS, Accept="text/html,application/xhtml+xml", Referer=BASE + "/")
        if self.ua:
            h["User-Agent"] = self.ua
        if self.cookie:
            h["Cookie"] = self.cookie
        return h

    def _download_headers(self):
        h = dict(BROWSER_HEADERS, Referer=BASE + "/")
        if self.ua:
            h["User-Agent"] = self.ua
        if self.cookie:
            h["Cookie"] = self.cookie
        return h

    def _get_page(self, url):
        try:
            text = self._open(url).decode("utf-8", "replace")
        except urllib.error.HTTPError as ex:
            if ex.code in (401, 403, 429):
                raise ApiError(BLOCK_HELP + f" (HTTP {ex.code})")
            raise
        if "not a bot" in text.lower() and "thumb_square" not in text:
            raise ApiError(BLOCK_HELP)
        return text

    def _page(self, query, cursor):
        page = cursor or 1
        qs = {"query": query}
        if page > 1:
            qs["page"] = page
        text = self._get_page(f"{BASE}/search/index?{urllib.parse.urlencode(qs)}")
        posts, has_next = parse_results(text)
        return posts, (page + 1 if has_next and posts else None)

    def _resolve_url(self, post, log):
        """The thumbnail grid only links to each picture's own page; the full-size file is named there."""
        try:
            text = self._get_page(BASE + post["path"])
        except Exception as ex:
            log(f"   -> couldn't open picture page {post['id']}: {self._explain(ex)}", "warning")
            return None
        m = (re.search(r'<meta property="og:image" content="([^"]+)"', text)
             or re.search(r"(?:https?:)?//pictures\.hentai-foundry\.com/[^\"'\s<>]+", text))
        if not m:
            log(f"   -> no full-size image found on picture page {post['id']}", "warning")
            return None
        url = html.unescape(m.group(1) if m.lastindex else m.group(0))
        return "https:" + url if url.startswith("//") else url

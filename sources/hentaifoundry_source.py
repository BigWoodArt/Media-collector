"""Hentai Foundry search.
The site shows a "making sure you're not a bot" page to scripts. This source does NOT try to get around it: in
Settings, "Connect browser" opens a real browser window, you pass the check yourself, and the session's cookies and
User-Agent are reused here (core/browser_session.py). Pasting a Cookie header by hand still works. The cookie expires;
connect again when searches stop working. Requests are slow (about 2.5 s apart)."""
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
BLOCK_HELP = ("Hentai Foundry's bot check stopped this request. In Settings, click Connect browser next to the "
              "Hentai Foundry cookie, pass the check in the window that opens, then Save (it expires, so redo this when needed).")
BLOCK_RE = re.compile(r'<div\b[^>]*class\s*=\s*["\'][^"\']*\bthumb_square\b[^"\']*["\'][^>]*>(.*?)(?=<div\b[^>]*class\s*=\s*["\'][^"\']*\bthumb_square\b|<div\b[^>]*class\s*=\s*["\'][^"\']*\bpagebar\b|$)', re.S | re.I)
LINK_RE = re.compile(r'<a\b(?=[^>]*\bclass\s*=\s*["\'][^"\']*\bthumbLink\b[^"\']*["\'])(?=[^>]*\bhref\s*=\s*["\'](/pictures/user/([^/"\']+)/(\d+)[^"\']*)["\'])[^>]*>', re.I)
TITLE_RE = re.compile(r'<span\b(?=[^>]*\bclass\s*=\s*["\'][^"\']*\bthumb\b[^"\']*["\'])(?=[^>]*\btitle\s*=\s*["\']([^"\']*)["\'])[^>]*>', re.I)
RATING_RE = re.compile(r'<[^>]*\bclass\s*=\s*["\'][^"\']*\brating\b[^"\']*["\'][^>]*\btitle\s*=\s*["\']([^"\']*)["\'][^>]*>', re.I)


def parse_results(page):
    """-> (posts, has_next).

    The site has changed its thumbnail wrappers over time. The stable part is
    the /pictures/user/<name>/<id>/ link, so use that as the fallback.
    """
    posts = []
    seen = set()
    blocks = BLOCK_RE.findall(page)
    if not blocks:
        blocks = re.split(r'(?=<a\b[^>]*href\s*=)', page, flags=re.I)

    for block in blocks:
        m = LINK_RE.search(block)
        if not m:
            m = re.search(
                r'<a\b[^>]*href\s*=\s*["\']'
                r'(/pictures/user/([^/"\']+)/(\d+)(?:/[^"\']*)?)'
                r'["\'][^>]*>', block, re.I)
        if not m:
            continue
        path, user, pid = m.group(1), m.group(2), m.group(3)
        if pid in seen:
            continue
        seen.add(pid)

        t = TITLE_RE.search(block)
        if not t:
            t = re.search(
                r'<(?:span|img)\b[^>]*\btitle\s*=\s*["\']([^"\']*)',
                block, re.I)
        title = html.unescape(t.group(1)) if t else ""
        ratings = RATING_RE.findall(block)
        posts.append({
            "id": pid,
            "url": "pending:" + path,
            "path": path,
            "user": user,
            "tags": [],
            "title": title,
            "text": " ".join([title, user] + ratings),
        })

    has_next = bool(re.search(
        r'<li\b[^>]*class\s*=\s*["\'][^"\']*\bnext\b[^"\']*["\'][^>]*>',
        page, re.I))
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
        self.user_agent = user_agent.strip() or BROWSER_HEADERS["User-Agent"]   # must match the browser that passed

    def _headers(self):
        h = dict(BROWSER_HEADERS, Accept="text/html,application/xhtml+xml", Referer=BASE + "/")
        h["User-Agent"] = self.user_agent
        if self.cookie:
            h["Cookie"] = self.cookie
        return h

    def _download_headers(self):
        h = dict(BROWSER_HEADERS, Referer=BASE + "/")
        h["User-Agent"] = self.user_agent
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
        """Picture page -> full-size image URL."""
        try:
            text = self._get_page(BASE + post["path"])
        except Exception as ex:
            log(f"   -> couldn't open picture page {post['id']}: {self._explain(ex)}", "warning")
            return None

        m = re.search(
            r"""<meta\b(?=[^>]*\bproperty\s*=\s*["']og:image["'])
            (?=[^>]*\bcontent\s*=\s*["']([^"']+)["'])[^>]*>""",
            text, re.I | re.X)
        if not m:
            m = re.search(
                r"""(?:https?:)?//pictures\.hentai-foundry\.com/[^"'\s<>]+""",
                text, re.I)
        if not m:
            m = re.search(
                r"""\b(?:data-original|data-src|src)\s*=\s*["']((?:https?:)?//pictures\.hentai-foundry\.com/[^"']+)["']""",
                text, re.I)
        if not m:
            log(f"   -> no full-size image found on picture page {post['id']}", "warning")
            return None
        url = html.unescape(m.group(1) if m.lastindex else m.group(0))
        return "https:" + url if url.startswith("//") else url

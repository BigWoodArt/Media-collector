"""HypnoTube (hypnotube.com) - public pages, no login. Videos only.
Search words:  spiral          keyword search (the site limits searches, so this one runs slowly)
               channel:11/hypnosis   one category (use the pick-list to find them)
Order: best match / newest / top rated / most viewed.  Quality: HD only, or a minimum like-percentage
(filtered here from the numbers each result shows)."""
import html
import http.cookiejar
import re
import time
import urllib.parse
import urllib.request

from core.safety import is_blocked
from sources.json_board import JsonBoardSource, ApiError

_FILTER = re.compile(r"\b(hd|minrating):(\d+)\b", re.I)
_CARD = re.compile(r'<a href="(https?://hypnotube\.com/video/[a-z0-9\-]*?-(\d+)\.html)"[^>]*title="([^"]*)"[^>]*>(.*?)</a>',
                   re.S | re.I)
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


class HypnoTubeSource(JsonBoardSource):
    id, label = "hypnotube", "HypnoTube"
    category = "Videos"
    check_query = "spiral"
    base_url = "https://hypnotube.com"
    prefix = "ht_"
    page_size = 20
    min_interval = 1.0
    search_gap = 3.2                        # the site answers "Search error" to searches that come faster
    has_media_priority = False
    priority_media = "video"
    query_hint = "words, or channel:id/name"
    user_agent = _UA
    order_choices = [
        ("best", "Best match / default", {"sort": ""}),
        ("new", "Newest", {"sort": "newest"}),
        ("rating", "Top rated", {"sort": "rating"}),
        ("views", "Most viewed", {"sort": "views"}),
    ]
    default_order = "best"
    order_help = "Search results can be re-ordered; channel lists use the site's order when no other is offered."
    min_score_choices = [
        ("", "Any quality", {}),
        ("hd", "HD only", {"query_suffix": "hd:1"}),
        ("r70", "70%+ liked", {"query_suffix": "minrating:70"}),
        ("r85", "85%+ liked", {"query_suffix": "minrating:85"}),
        ("hd85", "HD and 85%+", {"query_suffix": "hd:1 minrating:85"}),
    ]

    def __init__(self, api_key="", user_id=""):
        super().__init__(api_key, user_id)
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))
        self._last_search = 0.0

    # ---- find
    @classmethod
    def suggest(cls, query):
        q = (query or "").strip().lower()
        if not q:
            return []
        out = [{"value": query.strip(), "label": f"HypnoTube {query.strip()}", "count": None, "nofilter": True}]
        try:
            req = urllib.request.Request(cls.base_url + "/channels/", headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=8) as r:
                page = r.read().decode("utf-8", "replace")
        except Exception:
            return out
        seen = set()
        for cid, slug, inner in re.findall(r'href="(?:https?://hypnotube\.com)?/channels/(\d+)/([^/"]+)/"[^>]*>(.*?)</a>',
                                           page, re.S):
            text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner))).strip()
            m = re.match(r"^(.*?)\s*(\d+)?$", text)
            name, count = (m.group(1).strip(), int(m.group(2)) if m.group(2) else None) if m else (text, None)
            if not name or cid in seen or q not in name.lower():
                continue
            seen.add(cid)
            out.append({"value": f"channel:{cid}/{slug}", "label": f"HypnoTube {name} (channel)", "count": count,
                        "nofilter": True})
        return out

    # ---- http (cookies matter: the search keeps your last query in a session)
    def _get_text(self, url, data=None, timeout=20):
        self._wait()
        headers = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9", "Referer": self.base_url + "/"}
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, headers=headers)
        with self._opener.open(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")

    def _search_wait(self):
        gap = time.time() - self._last_search
        if gap < self.search_gap:
            time.sleep(self.search_gap - gap)
        self._last_search = time.time()

    # ---- parsing
    def _parse(self, query):
        filters = {m.group(1).lower(): int(m.group(2)) for m in _FILTER.finditer(query)}
        rest = _FILTER.sub(" ", query).strip()
        if rest.lower().startswith("channel:"):
            return "channel", rest[8:].strip().strip("/"), filters
        return "search", rest, filters

    @staticmethod
    def _cards(page):
        posts = []
        for url, vid, title, inner in _CARD.findall(page):
            quality = re.search(r'quality-icon[^>]*>([^<]*)<', inner)
            rate = re.search(r's-e-rate.*?(\d+)%', inner, re.S)
            posts.append({"id": vid, "page": url, "url": url, "title": html.unescape(title).strip(),
                          "hd": bool(quality and quality.group(1).strip().upper() in ("HD", "FHD", "4K", "UHD")),
                          "rating": int(rate.group(1)) if rate else None, "tags": []})
        return posts

    def _page(self, query, cursor):
        page_no = cursor or 1
        mode, term, filters = self._parse(query)
        sort = getattr(self, "_sort", None) or ""
        if mode == "search" and not term:
            raise ApiError("type a search word, or channel:id/name")
        if mode == "channel" and not re.match(r"^\d+/[a-z0-9\-]+$", term):
            raise ApiError("channel searches look like channel:11/hypnosis - use the pick-list")
        for _ in range(6):                      # a page with nothing that passes the quality filter: look further on
            if mode == "search":
                text = self._search_html(term, sort, page_no)
            else:
                path = f"/channels/{term}/" + (f"{sort}/" if sort in ("rating", "views") else "")
                path += f"page{page_no}.html" if page_no > 1 else ""
                text = self._get_text(self.base_url + path)
            posts = self._cards(text)
            more = bool(posts) and (f"page{page_no + 1}.html" in text)
            out = [p for p in posts
                   if not (filters.get("hd") and not p["hd"])
                   and not (filters.get("minrating") and (p["rating"] or 0) < filters["minrating"])]
            if out or not more:
                return out, (page_no + 1 if more else None)
            page_no += 1
        return [], None

    def _post_search(self, term):
        return self._get_text(self.base_url + "/searchgate.php",
                              urllib.parse.urlencode({"q": term, "type": ""}).encode())

    def _search_html(self, term, sort, page_no):
        """The site keeps your last query in a session and answers searches that come too fast with an error page,
        so: pace every request, POST the query (that answers page 1), and page through with plain GETs."""
        slug = urllib.parse.quote(term, safe="")
        path = f"/search/{slug}/" + (f"{sort}/" if sort else "") + (f"page{page_no}.html" if page_no > 1 else "")
        for attempt in range(3):
            self._search_wait()
            if page_no == 1 and not sort:
                text = self._post_search(term)
            elif attempt == 0:
                text = self._get_text(self.base_url + path)
            else:                               # session lost: say the query again, then ask for the page
                self._post_search(term)
                self._search_wait()
                text = self._get_text(self.base_url + path)
            if "/video/" in text or "Search error" not in text:
                return text
        raise ApiError("the site refused the search (it limits how fast searches may come) - try again in a minute")

    # ---- the file
    def _resolve_url(self, post, log):
        try:
            text = self._get_text(post["page"])
        except Exception as ex:
            log(f"   -> couldn't open the video page {post['id']}: {self._explain(ex)}", "warning")
            return None
        kw = re.search(r'<meta[^>]+name="keywords"[^>]+content="([^"]*)"', text, re.I)
        tags = [t.strip() for t in html.unescape(kw.group(1)).split(",") if t.strip()] if kw else []
        if is_blocked(tags):
            return None
        best, best_size = None, -1
        for tag in re.findall(r"<source\b[^>]*>", text, re.I):
            src = re.search(r'src="([^"]+)"', tag)
            if not src or "blank.mp4" in src.group(1):
                continue
            size = re.search(r'sizes="?(\d+)', tag)
            n = int(size.group(1)) if size else 0
            if n > best_size:
                best, best_size = html.unescape(src.group(1)), n
        if not best:
            log(f"   -> no playable file found for {post['id']}", "warning")
        return best

    def _download_headers(self):
        return {"User-Agent": _UA, "Referer": self.base_url + "/"}

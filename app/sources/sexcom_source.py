"""Sex.com pictures and GIFs.
The site is a Next.js app: the first page of results is embedded in the page's own data, later pages come from
its search API (/portal/api/<pictures|gifs>/search). Plain requests, no login; images are public CDN files."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from sources.json_board import JsonBoardSource, ApiError

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
ITEM_RE = re.compile(r'\{"id":(\d+),"externalId":(\d+),"uri":"(/images/[^"]+)","title":"((?:[^"\\]|\\.)*)"')


def parse_items(text):
    """Pull posts out of the page's embedded data (or any text holding the same JSON objects)."""
    t = text.replace('\\"', '"')
    out = []
    for m in ITEM_RE.finditer(t):
        raw = m.group(4)
        try:
            title = json.loads('"' + raw + '"')
        except ValueError:
            title = raw
        out.append({"id": m.group(2), "uri": m.group(3), "title": title})
    return out


class _SexCom(JsonBoardSource):
    category = "Sex.com"
    kind = "pictures"            # API/page path segment
    page_path = "pics"
    base_url = "https://www.sex.com"
    default_img_host = "https://imagex1.sx.cdn.live"
    page_size = 40
    min_interval = 1.5
    has_media_priority = False
    default_limit = 40
    check_query = "cat"
    query_hint = "search word (e.g. cat)"
    order_choices = [("popular", "Most popular", {"sort": "likeCount"}),
                     ("new", "Newest", {"sort": "publishedAt"})]
    default_order = "popular"
    min_score_choices = []
    order_help = "Most popular = most liked. Newest = latest uploads. Straight category. About 40 items per page."

    def __init__(self, api_key="", user_id=""):
        super().__init__(api_key, user_id)
        self._img_host, self._pages = self.default_img_host, 1

    @classmethod
    def suggest(cls, query):
        """One entry for the word, with the site's own result count. The first results page is fetched to confirm
        something matches: none -> not listed; page unreachable -> listed without a number. Never raises."""
        q = query.strip()
        if not q:
            return []
        entry = {"value": q, "label": f"{cls.label} {q}", "count": None}
        try:
            qs = urllib.parse.urlencode({"search": q})
            req = urllib.request.Request(f"{cls.base_url}/en/{cls.page_path}?{qs}",
                                         headers=dict(BROWSER_HEADERS, Accept="text/html"))
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as ex:
            return [] if ex.code == 404 else [entry]
        except Exception:
            return [entry]
        if "Just a moment" in raw[:2000]:
            return [entry]
        if not parse_items(raw):
            return []
        m = re.search(r'paging\\?":\{\\?"total\\?":(\d+)', raw)
        if m:
            entry["count"] = int(m.group(1))
        return [entry]

    def _headers(self):
        return dict(BROWSER_HEADERS, Accept="application/json, text/plain, */*",
                    Referer=f"{self.base_url}/en/{self.page_path}")

    def _download_headers(self):
        return dict(BROWSER_HEADERS, Referer=self.base_url + "/")

    def _page(self, query, cursor):
        page = cursor or 1
        order = getattr(self, "_sort", None) or "likeCount"
        if page == 1:
            qs = urllib.parse.urlencode({"search": query, "order": order})
            raw = self._open(f"{self.base_url}/en/{self.page_path}?{qs}",
                             headers=dict(BROWSER_HEADERS, Accept="text/html")).decode("utf-8", "replace")
            m = re.search(r'staticPinImageDomain\\?":\\?"(https://[^"\\]+)', raw)
            if m:
                self._img_host = m.group(1)
            m = re.search(r'numberOfPages\\?":(\d+)', raw)
            self._pages = int(m.group(1)) if m else 1
            items = parse_items(raw)
            if not items and "Just a moment" in raw[:2000]:
                raise ApiError("got a browser-check page instead of results")
        else:
            qs = urllib.parse.urlencode({"search": query, "page": page, "limit": self.page_size,
                                         "order": order, "sexual-orientation": "straight"})
            url = f"{self.base_url}/portal/api/{self.kind}/search?{qs}"
            try:
                raw = self._open(url).decode("utf-8", "replace")
            except Exception as ex:
                raise ApiError(f"page {page} was refused by the site's search API ({self._explain(ex)})")
            try:
                data = json.loads(raw)
                items = data.get("items") or data.get("data") or data if isinstance(data, (dict, list)) else []
                if isinstance(items, dict):
                    items = items.get("items") or []
                items = [{"id": str(i.get("externalId") or i.get("id")), "uri": i.get("uri"),
                          "title": i.get("title") or ""} for i in items if isinstance(i, dict) and i.get("uri")]
            except ValueError:
                items = parse_items(raw)
        posts = [{"id": i["id"], "url": self._img_host + i["uri"], "tags": [], "title": i["title"],
                  "text": i["title"]} for i in items]
        return posts, (page + 1 if page < self._pages and items else None)


class SexComPicsSource(_SexCom):
    id, label = "sexcom_pics", "Sex.com Pics"
    prefix = "sxp_"


class SexComGifsSource(_SexCom):
    id, label = "sexcom_gifs", "Sex.com GIFs"
    kind, page_path = "gifs", "gifs"
    prefix = "sxg_"

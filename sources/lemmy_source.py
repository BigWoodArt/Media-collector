import os
import urllib.parse

from sources.json_board import JsonBoardSource, ApiError, VIDEO_EXTS

IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp") + VIDEO_EXTS


class LemmySource(JsonBoardSource):
    """Lemmy communities (federated Reddit-style). Query: 'community' or 'community@instance.tld'.
    NSFW posts are hidden from anonymous callers: put a login token in Options (api_key) and enable NSFW on that
    account. 'instance' is the default home instance for bare community names."""
    id, label = "lemmy", "Lemmy"
    category = "Communities"
    check_query = "cats"
    prefix = "lm_"
    page_size = 40
    min_interval = 1.5
    order_choices = [
        ("hot", "Hot", {"sort": "Hot"}),
        ("new", "New", {"sort": "New"}),
        ("top_day", "Top today", {"sort": "TopDay"}),
        ("top_week", "Top this week", {"sort": "TopWeek"}),
        ("top_month", "Top this month", {"sort": "TopMonth"}),
        ("top_year", "Top this year", {"sort": "TopYear"}),
        ("top_all", "Top all time", {"sort": "TopAll"}),
    ]
    default_order = "top_month"
    min_score_choices = []
    query_hint = "community or community@instance"
    DEFAULT_INSTANCE = "lemmy.world"

    def __init__(self, api_key="", instance=""):
        super().__init__(api_key=api_key)
        self.instance = (instance or self.DEFAULT_INSTANCE).strip().replace("https://", "").strip("/")

    def _headers(self):
        h = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _split(self, query):
        name, _, host = query.strip().lstrip("!").partition("@")
        return name.strip(), (host.strip() or self.instance)

    def _page(self, query, cursor):
        name, host = self._split(query)
        page = cursor or 1
        params = {"community_name": f"{name}@{host}" if host != self.instance else name,
                  "sort": getattr(self, "_sort", None) or "TopMonth",
                  "limit": self.page_size, "page": page, "type_": "All"}
        data = self._get_json(f"https://{self.instance}/api/v3/post/list?{urllib.parse.urlencode(params)}")
        if isinstance(data, dict) and data.get("error"):
            raise ApiError(str(data["error"]))
        rows = data.get("posts") or []
        posts = []
        for r in rows:
            p = r.get("post") or {}
            url = p.get("url") or ""
            ctype = p.get("url_content_type") or ""
            ext = os.path.splitext(url.split("?")[0])[1].lower()
            if url and (ext in IMG_EXTS or ctype.startswith(("image/", "video/"))):
                posts.append({"id": p["id"], "url": url, "tags": [], "title": p.get("name") or "",
                              "text": p.get("name") or ""})
        return posts, (page + 1 if len(rows) >= self.page_size else None)

    def _download_headers(self):
        return {"User-Agent": self.user_agent}

    @classmethod
    def suggest(cls, query):
        qs = urllib.parse.urlencode({"q": query.strip(), "type_": "Communities", "sort": "TopAll", "limit": 8})
        data = cls._suggest_json(f"https://{cls.DEFAULT_INSTANCE}/api/v3/search?{qs}")
        out = []
        for c in (data or {}).get("communities") or []:
            comm = c.get("community") or {}
            host = urllib.parse.urlparse(comm.get("actor_id") or "").netloc
            if comm.get("name") and host:
                out.append({"value": f"{comm['name']}@{host}", "label": f"Lemmy !{comm['name']}@{host}",
                            "count": (c.get("counts") or {}).get("subscribers")})
        return out

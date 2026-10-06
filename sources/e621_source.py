import base64
import urllib.parse

from sources.json_board import JsonBoardSource, ApiError


class E621Source(JsonBoardSource):
    """e621.net - official JSON API. Needs a descriptive User-Agent (never a browser one); hard limit 2 req/s."""
    id, label = "e621", "e621"
    check_query = "cat"
    base_url = "https://e621.net"
    prefix = "e6_"
    page_size = 100
    min_interval = 0.6
    quality_scores = {"Good": 50, "Best": 200}
    query_hint = "tags (e.g. cat solo)"

    def _headers(self):
        who = f" (by {self.user_id} on e621)" if self.user_id else ""
        h = {"User-Agent": f"MediaCollector/0.2{who}", "Accept": "application/json"}
        if self.user_id and self.api_key:
            token = base64.b64encode(f"{self.user_id}:{self.api_key}".encode()).decode()
            h["Authorization"] = f"Basic {token}"
        return h

    def _download_headers(self):
        return self._headers()

    def _page(self, query, cursor):
        page = cursor or 1
        qs = urllib.parse.urlencode({"tags": query, "limit": self.page_size, "page": page})
        data = self._get_json(f"{self.base_url}/posts.json?{qs}")
        if isinstance(data, dict) and data.get("success") is False:
            raise ApiError(data.get("message") or data.get("reason") or "the API reported an error")
        posts = []
        for p in (data.get("posts") if isinstance(data, dict) else data) or []:
            url = (p.get("file") or {}).get("url")
            if not url:           # hidden by the site's global blacklist or needs a login
                continue
            tags = [t for group in (p.get("tags") or {}).values() for t in group]
            posts.append({"id": p["id"], "url": url, "tags": tags})
        raw_count = len(data.get("posts") or []) if isinstance(data, dict) else 0
        return posts, (page + 1 if raw_count >= self.page_size else None)

    @classmethod
    def suggest(cls, query):
        q = urllib.parse.urlencode({"search[name_matches]": query.strip().replace(" ", "_") + "*"})
        data = cls._suggest_json(f"{cls.base_url}/tags/autocomplete.json?{q}",
                                 {"User-Agent": "MediaCollector/0.2"})
        return [{"value": t["name"], "label": f"e621 {t['name']}", "count": t.get("post_count")}
                for t in (data or []) if isinstance(t, dict) and t.get("name")][:8]

import urllib.parse

from sources.json_board import JsonBoardSource, ApiError


class CivitaiSource(JsonBoardSource):
    """Civitai public REST API (/api/v1/images). Query: 'user:NAME', 'model:ID', or a model name to search.
    Mature content needs an API key. If NSFW lives on another host (e.g. a .red domain), change base_url."""
    id, label = "civitai", "Civitai"
    category = "AI art"
    check_query = "user:Civitai"
    base_url = "https://civitai.com"
    prefix = "cv_"
    page_size = 100
    min_interval = 1.5
    order_choices = [
        ("reactions_week", "Most reactions this week", {"sort": "Most Reactions", "time_range": "Week"}),
        ("reactions_month", "Most reactions this month", {"sort": "Most Reactions", "time_range": "Month"}),
        ("reactions_year", "Most reactions this year", {"sort": "Most Reactions", "time_range": "Year"}),
        ("reactions_all", "Most reactions all time", {"sort": "Most Reactions", "time_range": "AllTime"}),
        ("comments_month", "Most comments this month", {"sort": "Most Comments", "time_range": "Month"}),
        ("new", "Newest", {"sort": "Newest"}),
    ]
    default_order = "reactions_month"
    min_score_choices = []
    query_hint = "user:name, model:id, or model name"
    TIME_PERIODS = ("Day", "Week", "Month", "Year", "AllTime")
    DEFAULT_SORT = "Most Reactions"

    def _headers(self):
        h = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _resolve_target(self, query):
        q = query.strip()
        if q.lower().startswith("user:"):
            return {"username": q[5:].strip()}
        if q.lower().startswith("model:") and q[6:].strip().isdigit():
            return {"modelId": q[6:].strip()}
        data = self._get_json(f"{self.base_url}/api/v1/models?" + urllib.parse.urlencode({"query": q, "limit": 1}))
        items = data.get("items") or []
        if not items:
            raise ApiError(f"no Civitai model matches '{q}' (try user:NAME or model:ID)")
        return {"modelId": items[0]["id"]}

    def _page(self, query, cursor):
        if not hasattr(self, "_target") or self._target_for != query:
            self._target, self._target_for = self._resolve_target(query), query
        params = dict(self._target, limit=self.page_size,
                      sort=getattr(self, "_sort", None) or self.DEFAULT_SORT)
        period = getattr(self, "_time", None)
        if period in self.TIME_PERIODS:
            params["period"] = period
        if cursor:
            params["cursor"] = cursor
        data = self._get_json(f"{self.base_url}/api/v1/images?{urllib.parse.urlencode(params)}")
        posts = []
        for i in data.get("items") or []:
            meta = i.get("meta") if isinstance(i.get("meta"), dict) else {}
            posts.append({"id": i["id"], "url": i.get("url"), "tags": [],
                          "text": str(meta.get("prompt") or ""),
                          "title": f"civitai {i['id']}"})
        nxt = (data.get("metadata") or {}).get("nextCursor")
        return [p for p in posts if p["url"]], (str(nxt) if nxt else None)

    @classmethod
    def suggest(cls, query):
        qs = urllib.parse.urlencode({"query": query.strip(), "limit": 8})
        data = cls._suggest_json(f"{cls.base_url}/api/v1/models?{qs}")
        out = []
        for m in (data or {}).get("items") or []:
            dl = (m.get("stats") or {}).get("downloadCount")
            out.append({"value": f"model:{m['id']}", "label": f"Civitai model: {m.get('name')}", "count": dl})
        return out

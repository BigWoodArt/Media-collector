import urllib.parse

from sources.json_board import JsonBoardSource


class WallhavenSource(JsonBoardSource):
    """wallhaven.cc - official API. NSFW purity needs a (free) API key from your account settings."""
    id, label = "wallhaven", "Wallhaven"
    category = "Wallpapers"
    check_query = "cats"
    base_url = "https://wallhaven.cc"
    prefix = "wh_"
    page_size = 24
    min_interval = 1.0
    has_media_priority = False        # images only
    order_choices = [
        ("relevance", "Best match", {"sort": "relevance"}),
        ("hot", "Hot", {"sort": "hot"}),
        ("favorites", "Most favorited", {"sort": "favorites"}),
        ("views", "Most viewed", {"sort": "views"}),
        ("top_week", "Top this week", {"sort": "toplist", "time_range": "1w"}),
        ("top_month", "Top this month", {"sort": "toplist", "time_range": "1M"}),
        ("top_year", "Top this year", {"sort": "toplist", "time_range": "1y"}),
        ("new", "Newest", {"sort": "date_added"}),
        ("random", "Random", {"sort": "random"}),
    ]
    default_order = "relevance"
    min_score_choices = []
    query_hint = "keywords or tags (e.g. cat girl)"

    def _page(self, query, cursor):
        page = cursor or 1
        params = {"q": query, "page": page, "categories": "111",
                  "purity": "011" if self.api_key else "100",
                  "sorting": getattr(self, "_sort", None) or "relevance"}
        if params["sorting"] == "toplist":
            params["topRange"] = getattr(self, "_time", None) or "1y"
        if self.api_key:
            params["apikey"] = self.api_key
        data = self._get_json(f"{self.base_url}/api/v1/search?{urllib.parse.urlencode(params)}")
        items = data.get("data") or []
        meta = data.get("meta") or {}
        posts = [{"id": i["id"], "url": i["path"], "tags": []} for i in items if i.get("path")]
        more = int(meta.get("current_page") or page) < int(meta.get("last_page") or page)
        return posts, (page + 1 if more else None)

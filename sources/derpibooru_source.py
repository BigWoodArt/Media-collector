import urllib.parse

from sources.json_board import JsonBoardSource


class DerpibooruSource(JsonBoardSource):
    """derpibooru.org - Philomena API. filter_id picks what's visible; EVERYTHING_FILTER shows explicit images."""
    id, label = "derpibooru", "Derpibooru"
    check_query = "safe"
    base_url = "https://derpibooru.org"
    prefix = "dp_"
    page_size = 50
    EVERYTHING_FILTER = 56027      # verify with Check all sites; the site's "Everything" filter
    quality_scores = {"Good": 100, "Best": 500}
    query_hint = "tags, comma-separated (e.g. explicit, solo)"

    @classmethod
    def resolve_quality(cls, quality):
        n = cls.quality_scores.get(quality)
        return {"query_suffix": f"score.gte:{n}"} if n else {}

    def _page(self, query, cursor):
        page = cursor or 1
        params = {"q": query or "*", "per_page": self.page_size, "page": page,
                  "filter_id": self.EVERYTHING_FILTER, "sf": "score", "sd": "desc"}
        if self.api_key:
            params["key"] = self.api_key
        data = self._get_json(f"{self.base_url}/api/v1/json/search/images?{urllib.parse.urlencode(params)}")
        imgs = data.get("images") or []
        posts = [{"id": i["id"], "url": (i.get("representations") or {}).get("full"),
                  "tags": i.get("tags") or []} for i in imgs]
        return [p for p in posts if p["url"]], (page + 1 if len(imgs) >= self.page_size else None)

    @classmethod
    def suggest(cls, query):
        qs = urllib.parse.urlencode({"q": query.strip() + "*"})
        data = cls._suggest_json(f"{cls.base_url}/api/v1/json/search/tags?{qs}")
        return [{"value": t["name"], "label": f"Derpibooru {t['name']}", "count": t.get("images")}
                for t in ((data or {}).get("tags") or [])[:8] if t.get("name")]

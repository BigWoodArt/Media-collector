import urllib.parse

from sources.json_board import JsonBoardSource, ApiError


class DanbooruSource(JsonBoardSource):
    """danbooru.donmai.us - official JSON API. Free/anonymous searches are limited to 2 tags."""
    id, label = "danbooru", "Danbooru"
    check_query = "cat_ears"
    base_url = "https://danbooru.donmai.us"
    prefix = "db_"
    page_size = 100
    quality_scores = {"Good": 20, "Best": 100}
    query_hint = "tags, max 2 (e.g. cat_ears solo)"

    def _auth(self):
        return {"login": self.user_id, "api_key": self.api_key} if self.user_id and self.api_key else {}

    def _page(self, query, cursor):
        page = cursor or 1
        params = {"tags": query, "limit": self.page_size, "page": page, **self._auth()}
        data = self._get_json(f"{self.base_url}/posts.json?{urllib.parse.urlencode(params)}")
        if isinstance(data, dict):
            msg = data.get("message") or data.get("error") or "the API reported an error"
            if "tags" in str(msg).lower():
                msg += " - free accounts can search 2 tags at a time; add login + API key in Options or use fewer tags"
            raise ApiError(msg)
        posts = []
        for p in data:
            url = p.get("file_url") or p.get("large_file_url")
            if url:
                posts.append({"id": p["id"], "url": url, "tags": (p.get("tag_string") or "").split()})
        return posts, (page + 1 if len(data) >= self.page_size else None)

    @classmethod
    def suggest(cls, query):
        q = urllib.parse.urlencode({"search[name_matches]": query.strip().replace(" ", "_") + "*",
                                    "search[order]": "count", "limit": 8})
        data = cls._suggest_json(f"{cls.base_url}/tags.json?{q}")
        return [{"value": t["name"], "label": f"Danbooru {t['name']}", "count": t.get("post_count")}
                for t in (data or []) if isinstance(t, dict) and t.get("name")]

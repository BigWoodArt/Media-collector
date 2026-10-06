import urllib.parse

from sources.json_board import JsonBoardSource


class MoebooruSource(JsonBoardSource):
    """Moebooru-engine boards: /post.json, page starts at 1, tags are a space-separated string."""
    page_size = 100
    quality_scores = {"Good": 20, "Best": 100}
    query_hint = "tags (e.g. cat_ears solo)"
    check_query = "cat_ears"

    def _page(self, query, cursor):
        page = cursor or 1
        qs = urllib.parse.urlencode({"tags": query, "limit": self.page_size, "page": page})
        data = self._get_json(f"{self.base_url}/post.json?{qs}")
        posts = [{"id": p["id"], "url": p["file_url"], "tags": (p.get("tags") or "").split()}
                 for p in data if isinstance(p, dict) and p.get("file_url")]
        return posts, (page + 1 if len(data) >= self.page_size else None)

    @classmethod
    def suggest(cls, query):
        qs = urllib.parse.urlencode({"name": query.strip().replace(" ", "_"), "order": "count", "limit": 8})
        data = cls._suggest_json(f"{cls.base_url}/tag.json?{qs}")
        return [{"value": t["name"], "label": f"{cls.label} {t['name']}", "count": t.get("count")}
                for t in (data or []) if isinstance(t, dict) and t.get("name")]


class YandereSource(MoebooruSource):
    id, label = "yandere", "Yande.re"
    base_url = "https://yande.re"
    prefix = "yd_"


class KonachanSource(MoebooruSource):
    id, label = "konachan", "Konachan"
    base_url = "https://konachan.com"
    prefix = "kc_"

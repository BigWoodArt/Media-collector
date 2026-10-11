import urllib.parse

from sources.json_board import JsonBoardSource, SCORE_ORDERS


class MoebooruSource(JsonBoardSource):
    """Moebooru-engine boards: /post.json, page starts at 1, tags are a space-separated string."""
    page_size = 100
    order_choices = SCORE_ORDERS
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
        q = query.strip().replace(" ", "_").lower()
        qs = urllib.parse.urlencode({"name_pattern": q, "order": "count", "limit": 30})
        data = cls._suggest_json(f"{cls.base_url}/tag.json?{qs}")
        rows = [t for t in (data or []) if isinstance(t, dict) and t.get("name") and q in t["name"].lower()]
        if not rows:                                    # fall back to the exact-name route
            qs = urllib.parse.urlencode({"name": q, "order": "count", "limit": 8})
            data = cls._suggest_json(f"{cls.base_url}/tag.json?{qs}")
            rows = [t for t in (data or []) if isinstance(t, dict) and t.get("name") and q in t["name"].lower()]
        rows.sort(key=lambda t: (not t["name"].lower().startswith(q), -(t.get("count") or 0)))
        return [{"value": t["name"], "label": f"{cls.label} {t['name']}", "count": t.get("count")}
                for t in rows[:8]]


class YandereSource(MoebooruSource):
    id, label = "yandere", "Yande.re"
    base_url = "https://yande.re"
    prefix = "yd_"


class KonachanSource(MoebooruSource):
    id, label = "konachan", "Konachan"
    base_url = "https://konachan.com"
    prefix = "kc_"

"""PMV Haven (pmvhaven.com) - the site's own JSON API, no login. Videos only.
Search words:  spiral            keyword search (best match)
               tag:Trans         videos carrying that tag   (also: tag:big ass)
               creator:Infinite  one uploader's videos
               (empty)           everything, in the chosen order
Order and quality only apply to tag / creator / browse lists; the keyword search always answers best match first."""
import re
import urllib.parse

from core.safety import is_blocked
from sources.json_board import JsonBoardSource

_FILTER = re.compile(r"\b(minheight|minrating):(\d+)\b", re.I)


class PmvHavenSource(JsonBoardSource):
    id, label = "pmvhaven", "PMV Haven"
    category = "Videos"
    check_query = "tag:Trans"
    base_url = "https://pmvhaven.com"
    prefix = "pmv_"
    page_size = 30
    min_interval = 1.0
    has_media_priority = False
    priority_media = "video"
    query_hint = "words, tag:name or creator:name"
    order_choices = [
        ("new", "Newest", {"sort": "-uploadDate"}),
        ("views", "Most viewed", {"sort": "-views"}),
        ("rated", "Best rated", {"sort": "-bayesianRating"}),
        ("liked", "Most liked", {"sort": "-likes"}),
    ]
    default_order = "new"
    order_help = "Newest, most viewed, best rated or most liked. Applies to tag:, creator: and empty searches."
    min_score_choices = [
        ("", "Any quality", {}),
        ("720", "720p or better", {"query_suffix": "minheight:720"}),
        ("1080", "1080p or better", {"query_suffix": "minheight:1080"}),
        ("r70", "70%+ rating", {"query_suffix": "minrating:70"}),
        ("r85", "85%+ rating", {"query_suffix": "minrating:85"}),
        ("hd85", "1080p and 85%+", {"query_suffix": "minheight:1080 minrating:85"}),
    ]

    @classmethod
    def suggest(cls, query):
        q = (query or "").strip()
        if not q:
            return []
        enc = urllib.parse.quote(q)
        out = []
        for value, label, url, key in (
                (q, f"PMV Haven {q}", f"{cls.base_url}/api/videos/search?q={enc}", "total"),
                (f"tag:{q}", f"PMV Haven {q} (tag)", f"{cls.base_url}/api/videos?limit=1&tags={enc}", "pagination"),
                (f"creator:{q}", f"PMV Haven {q} (creator)", f"{cls.base_url}/api/videos?limit=1&creator={enc}", "pagination")):
            data = cls._suggest_json(url)
            total = ((data or {}).get("pagination") or {}).get("total") or (data or {}).get("total")
            try:
                total = int(total)
            except (TypeError, ValueError):
                continue
            if total > 0:
                out.append({"value": value, "label": label, "count": total, "nofilter": True})
        return out

    def _parse(self, query):
        filters = {m.group(1).lower(): int(m.group(2)) for m in _FILTER.finditer(query)}
        rest = _FILTER.sub(" ", query).strip()
        low = rest.lower()
        if low.startswith("tag:"):
            return "tag", rest[4:].strip(), filters
        if low.startswith("creator:"):
            return "creator", rest[8:].strip(), filters
        return ("search" if rest else "browse"), rest, filters

    def _page(self, query, cursor):
        page = cursor or 1
        mode, term, filters = self._parse(query)
        if mode == "search":
            data = self._get_json(f"{self.base_url}/api/videos/search?" +
                                  urllib.parse.urlencode({"q": term, "page": page}))
            videos = data.get("videos") or []
            pg = data.get("pagination") or {}
            total = int(pg.get("total") or data.get("total") or 0)
            more = bool(pg.get("hasNext")) if "hasNext" in pg else (bool(videos) and page * len(videos) < total)
        else:
            params = {"page": page, "limit": self.page_size, "sort": getattr(self, "_sort", None) or "-uploadDate"}
            if mode == "tag":
                params["tags"] = term
            elif mode == "creator":
                params["creator"] = term
            if filters.get("minheight"):
                params["minHeight"] = filters["minheight"]
            if filters.get("minrating"):
                params["minRating"] = filters["minrating"]
            data = self._get_json(f"{self.base_url}/api/videos?" + urllib.parse.urlencode(params))
            videos = data.get("videos") or []
            more = bool((data.get("pagination") or {}).get("hasNext")) and bool(videos)
        posts = []
        for v in videos:
            if not v.get("_id"):
                continue
            # keyword-search rows carry no file link: the video's own record has it (see _resolve_url)
            posts.append({"id": v.get("_id"), "url": v.get("videoUrl") or f"{self.base_url}/api/videos/{v['_id']}",
                          "lookup": not v.get("videoUrl"), "tags": list(v.get("tags") or []) +
                          list(v.get("starsTags") or []), "title": v.get("title") or "",
                          "text": v.get("description") or ""})
        return posts, (page + 1 if more else None)

    def _resolve_url(self, post, log):
        if not post.get("lookup"):
            return post.get("url")
        try:
            data = (self._get_json(post["url"]) or {}).get("data") or {}
        except Exception as ex:
            log(f"   -> couldn't look up video {post.get('id')}: {self._explain(ex)}", "warning")
            return None
        if is_blocked(list(data.get("tags") or []) + list(data.get("starsTags") or [])) or is_blocked(data.get("description") or ""):
            return None
        if not data.get("videoUrl"):
            log(f"   -> no file for video {post.get('id')}", "warning")
        return data.get("videoUrl")

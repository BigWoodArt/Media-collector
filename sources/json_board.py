"""Shared engine for sites with a JSON API. A subclass supplies _page() (one request -> normalised posts) and
suggest(); this class does paging, pacing, dedupe, the safety guard, downloading and saving.
Normalised post: {"id": str, "url": str, "tags": [str], "title": str, "text": str (optional free text)}"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from core import netlog
from sources.base import Source
from core.media_item import MediaItem
from core.safety import is_blocked, query_blocked

VIDEO_EXTS = (".mp4", ".webm", ".mov", ".m4v")
AUDIO_EXTS = (".mp3", ".m4a", ".ogg", ".wav")


class ApiError(ValueError):
    """The API answered, but not usefully. str() is the reason shown in the log."""


def score_choices(values, template="score:>={n}"):
    """Min-score dropdown: Any, plus one choice per value."""
    return [("", "Any", {})] + [(str(n), f"{n}+", {"query_suffix": template.format(n=n)}) for n in values]


SCORE_ORDERS = [("score", "Highest score", {"query_suffix": "order:score"}), ("new", "Newest", {})]


class JsonBoardSource(Source):
    category = "Image boards"
    has_media_priority = True
    query_hint = "tags"
    order_choices = SCORE_ORDERS + [("random", "Random", {"query_suffix": "order:random"})]
    default_order = "score"
    min_score_choices = score_choices((5, 10, 25, 50, 100))

    base_url = ""
    prefix = ""
    user_agent = "MediaCollector/0.2 (personal media collector)"
    min_interval = 1.0
    page_size = 100

    def __init__(self, api_key="", user_id=""):
        self.api_key, self.user_id = api_key, user_id
        self._last = 0.0
        self.seen_hashes = set()

    # ---- hooks for subclasses
    def _page(self, query, cursor):
        """-> (posts, next_cursor). next_cursor None = last page. cursor starts as None."""
        raise NotImplementedError

    def _headers(self):
        h = {"User-Agent": self.user_agent, "Accept": "application/json"}
        return h

    def _normalize_query(self, query):
        """Hook: tidy the final query (e.g. join appended tokens with commas)."""
        return query

    # ---- http
    def _wait(self):
        gap = time.time() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.time()

    def _open(self, url, headers=None, timeout=20):
        self._wait()
        req = urllib.request.Request(url, headers=headers or self._headers())
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    def _get_json(self, url):
        raw = self._open(url)
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            snippet = re.sub(r"\s+", " ", raw[:160].decode("utf-8", "replace"))
            if "Just a moment" in snippet or "<html" in snippet.lower():
                raise ApiError(f"got a web page instead of data (browser check or block): {snippet!r}")
            raise ApiError(f"reply wasn't JSON: {snippet!r}")

    @classmethod
    def _suggest_json(cls, url, headers=None):
        """Helper for suggest(): fetch JSON, return None on any failure."""
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": cls.user_agent})
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            return None

    @staticmethod
    def _explain(ex):
        if isinstance(ex, urllib.error.HTTPError):
            if ex.code in (401, 403):
                return f"HTTP {ex.code} - access refused (a login/API key may be needed)"
            if ex.code == 429:
                return "HTTP 429 - rate limited"
            return f"HTTP {ex.code}"
        return str(ex)

    # ---- plugin entrypoint
    def fetch(self, query, limit, sort, time_range, dest_dir, log, progress, stop_event,
              early_preview_cb=None, randomize=False, prioritize_images=False,
              item_cb=None, skip_ids=None):
        query = (query or "").strip()
        self._sort, self._time = sort, time_range
        os.makedirs(dest_dir, exist_ok=True)
        if query_blocked(query):
            log(f"[{self.label}] that search asks for material this tool never collects - skipped.", "warning")
            return []
        query = self._normalize_query(query)
        log(f"Searching {self.label} for '{query}'...")
        results, images_kept, videos_kept = [], 0, 0
        cursor, scanned, page_no, blocked = None, 0, 0, 0
        seen_ids = set()
        while len(results) < limit and not stop_event.is_set():
            try:
                posts, nxt = self._page(query, cursor)
            except Exception as ex:
                log(f"[{self.label}] search request failed: {self._explain(ex)}", "error")
                break
            page_no += 1
            log(f"page {page_no}: {len(posts)} post(s)")
            if not posts:
                if page_no == 1:
                    log(f"No {self.label} results for '{query}' - the site answered but listed nothing.", "warning")
                break
            if randomize:
                import random
                posts = list(posts)
                random.shuffle(posts)
            fresh = 0
            for post in posts:
                if stop_event.is_set() or len(results) >= limit:
                    break
                scanned += 1
                progress(scanned, max(scanned, limit), f"Scanning {self.label}")
                pid, url = str(post.get("id") or ""), post.get("url") or ""
                if not pid or not url or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                fresh += 1
                if is_blocked(post.get("tags") or []) or is_blocked(post.get("text") or ""):
                    blocked += 1
                    continue
                if skip_ids and f"{self.prefix}{pid}" in skip_ids:
                    continue
                url = self._resolve_url(post, log)       # most sites already know it; some need a second page
                if not url:
                    continue
                ext = os.path.splitext(url.split("?")[0])[1].lower() or ".jpg"
                mtype = "video" if ext in VIDEO_EXTS else "audio" if ext in AUDIO_EXTS else "image"
                if prioritize_images and mtype == "video" and videos_kept * 4 >= images_kept:
                    continue
                wanted = getattr(self, "wanted_types", None)
                if wanted and mtype not in wanted:          # e.g. only Image ticked: don't download videos
                    continue
                if getattr(self, "_site_check", False):
                    if self._site_check_probe(url):
                        results.append(MediaItem(file_path="", caption=post.get("title") or f"{query} result",
                                                 media_type=mtype, source_label=f"{self.label}: {query}",
                                                 post_id=f"{self.prefix}{pid}", source_type=self.id,
                                                 extra={"site_check": True, "probe_url": url}))
                        break
                    log(f"   -> media probe failed for {pid}", "warning")
                    continue
                try:
                    content = self._open(url, headers=self._download_headers(), timeout=40)
                except Exception as ex:
                    log(f"   -> failed to fetch {pid}: {self._explain(ex)}", "warning")
                    continue
                digest = hashlib.md5(content).hexdigest()
                if digest in self.seen_hashes:
                    continue
                self.seen_hashes.add(digest)
                title = post.get("title") or ", ".join((post.get("tags") or [])[:6]) or f"{query} post"
                clean = re.sub(r'[\\/*?:"<>|]', "", title)[:40].strip() or self.id
                path = os.path.join(dest_dir, f"{clean}_{digest[:8]}{ext}")
                if not os.path.exists(path):
                    try:
                        with open(path, "wb") as f:
                            f.write(content)
                    except Exception as ex:
                        log(f"   -> failed to save {pid}: {ex}", "warning")
                        continue
                if mtype == "video":
                    videos_kept += 1
                else:
                    images_kept += 1
                log(f"[{len(results) + 1}] downloaded {pid}")
                results.append(MediaItem(file_path=path, caption=title, media_type=mtype,
                                         source_label=f"{self.label}: {query}", post_id=f"{self.prefix}{pid}",
                                         source_type=self.id))
                if item_cb is not None:
                    item_cb(results[-1])
                if early_preview_cb is not None and len(results) == 3:
                    early_preview_cb(list(results))
                    early_preview_cb = None
            if nxt is None:
                break
            if fresh == 0:
                log(f"page {page_no} repeated earlier posts - stopping", "warning")
                break
            cursor = nxt
        if blocked:
            log(f"{blocked} post(s) skipped by the built-in content guard.")
        progress(len(results), max(len(results), 1), "Done")
        log(f"--- {self.label} '{query}': {len(results)} item(s) collected ---")
        return results

    def _resolve_url(self, post, log):
        """Hook: the file URL for a post (default: the one the listing gave). Return None to skip the post."""
        return post.get("url")

    def _download_headers(self):
        return {"User-Agent": self.user_agent, "Referer": (self.base_url or "") + "/"}

    def _site_check_probe(self, url):
        """Probe a media URL without downloading the file. A site check only
        needs to know that the returned media endpoint answers; it must not
        pull a 500 MB video just to display a green check mark."""
        headers = dict(self._download_headers())
        headers["Range"] = "bytes=0-65535"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                resp.read(65536)
                return status in (200, 206)
        except Exception:
            return False

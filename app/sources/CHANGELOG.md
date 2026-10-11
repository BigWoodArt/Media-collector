## v0.1.8
- Site-check probes now read up to 10 MiB.

"""Kemono / Coomer creator scraper for MediaCollector.

The two sites expose the same API family.  This module intentionally uses the
public API and public media URLs rather than browser automation or access-control
workarounds.
"""
import gzip
import hashlib
import html
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from core import netlog
from sources.base import Source
from core.media_item import MediaItem

HEADERS = {
    "User-Agent": "MediaCollector/0.1.8 (public-media-source)",
    "Accept": "text/css",
    "Accept-Encoding": "identity",
}
POST_PAGE = 50
MIN_INTERVAL = 0.8
CREATOR_CACHE = {}
CREATOR_CACHE_TTL = 600
INLINE_RE = re.compile(
    r'(?:src="(?:https?://(?:kemono\.cr|coomer\.st))?)(/inline/[^" ]+|/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}\.[^" ]+)', re.I
)


def _safe(value, fallback="media"):
    value = re.sub(r'[\\/*?:"<>|]', "", str(value or ""))
    value = re.sub(r"\s+", " ", value).strip()
    return value[:100] or fallback


def _ext(url, name=""):
    for value in (name, urllib.parse.urlparse(url).path):
        ext = os.path.splitext(value)[1].lower()
        if ext:
            return ext
    return ".bin"


def _type(ext):
    if ext in {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"}:
        return "video"
    if ext in {".mp3", ".m4a", ".ogg", ".wav", ".flac", ".aac"}:
        return "audio"
    return "image"


class _KemonoFamily(Source):
    category = "Creator archives"
    default_limit = 20
    default_randomize = False
    priority_media = "image"
    default_prioritize = False
    has_media_priority = True
    order_choices = []
    min_score_choices = []
    default_order = ""
    check_query = "test"

    root = ""
    site_name = ""
    id = ""
    label = ""
    query_hint = "SERVICE/user/CREATOR or creator URL"

    def __init__(self):
        self._last_request = 0.0
        self.seen_hashes = set()

    def _wait(self):
        delay = MIN_INTERVAL - (time.time() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        self._last_request = time.time()

    def _request(self, url, timeout=20, referer=None):
        self._wait()
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            encoding = str(getattr(response, "headers", {}).get("Content-Encoding") or "").lower()
            if "gzip" in encoding:
                raw = gzip.decompress(raw)
            elif "deflate" in encoding:
                import zlib
                raw = zlib.decompress(raw)
            return raw

    def _json(self, url):
        raw = self._request(url)
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError as ex:
            snippet = re.sub(r"\s+", " ", raw[:240].decode("utf-8", "replace")).strip()
            raise ValueError(f"response was not JSON: {snippet!r}") from ex

    @classmethod
    def _creator_matches(cls, query):
        q = query.strip().lower()
        if not q:
            return []
        now = time.time()
        cached = CREATOR_CACHE.get(cls.id)
        if cached and now - cached[0] < CREATOR_CACHE_TTL:
            creators = cached[1]
        else:
            try:
                req = urllib.request.Request(cls.root + "/api/v1/creators", headers=HEADERS)
                with urllib.request.urlopen(req, timeout=12) as r:
                    creators = json.loads(r.read().decode("utf-8", "replace"))
                if not isinstance(creators, list):
                    creators = []
                CREATOR_CACHE[cls.id] = (now, creators)
            except Exception:
                return []
        out = []
        for c in creators:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "")
            service = str(c.get("service") or "")
            cid = str(c.get("id") or "")
            hay = f"{name} {service} {cid}".lower()
            if q not in hay or not service or not cid:
                continue
            fav = c.get("favorited")
            try:
                count = int(fav) if fav is not None else None
            except (ValueError, TypeError):
                count = None
            value = f"{service}/user/{cid}"
            out.append({
                "value": value,
                "label": f"{cls.label} {service}: {name or cid}",
                "count": count,
            })
        out.sort(key=lambda x: -(x["count"] or 0))
        return out[:12]

    @classmethod
    def suggest(cls, query):
        q = query.strip().strip("/")
        if not q:
            return []
        # The creators endpoint is occasionally blocked even while the post
        # API works. For an already-structured creator URL, or a bare Coomer
        # username, we can still offer an exact Find -> Match result without
        # pretending to know its follower count.
        if cls.id == "coomer" and len([p for p in q.split("/") if p]) == 1 and " " not in q:
            service, creator = cls._parse_query(q)
            return [{"value": f"{service}/user/{creator}",
                     "label": f"{cls.label} {service}: {creator}", "count": None, "nofilter": True}]
        if ("/user/" in q.lower()) and len([p for p in q.split("/") if p]) >= 3:
            service, creator = cls._parse_query(q)
            return [{"value": f"{service}/user/{creator}",
                     "label": f"{cls.label} {service}: {creator}", "count": None, "nofilter": True}]
        return cls._creator_matches(q)

    @classmethod
    def _parse_query(cls, query):
        q = query.strip()
        if q.startswith(("http://", "https://")):
            p = urllib.parse.urlparse(q)
            parts = [x for x in p.path.split("/") if x]
        else:
            parts = [x for x in q.strip("/").split("/") if x]
        if len(parts) >= 3 and parts[1].lower() == "user":
            return parts[0], parts[2]
        if len(parts) == 2 and parts[0] != "user":
            return parts[0], parts[1]
        # Coomer's primary service is OnlyFans. Accepting a bare creator name
        # makes the common "Coomer username" form usable in the Add box.
        if cls.id == "coomer" and len(parts) == 1:
            return "onlyfans", parts[0]
        raise ValueError("Use SERVICE/user/CREATOR, for example patreon/user/12345")

    def _media_url(self, path):
        path = str(path or "").replace("\\", "/")
        if not path:
            return ""
        if path.startswith("http://") or path.startswith("https://"):
            if path.startswith(self.root + "/data/"):
                return path
            if path.startswith(self.root + "/"):
                tail = path[len(self.root):]
                if tail.startswith("/data/"):
                    return path
                return self.root + "/data" + tail
            return path
        if path.startswith("/"):
            return self.root + "/data" + path
        return self.root + "/data/" + path

    @staticmethod
    def _post_data(raw):
        if isinstance(raw, dict) and isinstance(raw.get("post"), dict):
            return raw["post"]
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _files(post):
        out = []
        f = post.get("file")
        if isinstance(f, dict) and f.get("path"):
            out.append(("file", f))
        for a in post.get("attachments") or []:
            if isinstance(a, dict) and a.get("path"):
                out.append(("attachment", a))
        content = html.unescape(str(post.get("content") or ""))
        for path in INLINE_RE.findall(content):
            out.append(("inline", {"path": path, "name": path}))
        return out

    def fetch(self, query, limit, sort, time_range, dest_dir, log, progress, stop_event,
              early_preview_cb=None, randomize=False, prioritize_images=False,
              item_cb=None, skip_ids=None):
        os.makedirs(dest_dir, exist_ok=True)
        try:
            service, creator = self._parse_query(query)
        except ValueError as ex:
            log(f"[{self.label}] {ex}", "error")
            return []

        endpoint = f"{self.root}/api/v1/{urllib.parse.quote(service, safe='')}/user/{urllib.parse.quote(creator, safe='')}/posts"
        log(f"[{self.label}] endpoint: {endpoint}?o=0", "debug")
        log(f"Fetching {self.label} {service}/user/{creator}...")
        results = []
        offset = 0
        post_count = 0
        while len(results) < limit and not stop_event.is_set():
            url = endpoint + "?" + urllib.parse.urlencode({"o": offset})
            try:
                data = self._json(url)
            except urllib.error.HTTPError as ex:
                try:
                    body = ex.read(220).decode("utf-8", "replace").replace("\\n", " ")
                except Exception:
                    body = ""
                detail = f" body={body!r}" if body else ""
                log(f"[{self.label}] API HTTP {ex.code}: {url}{detail}", "error")
                break
            except Exception as ex:
                log(f"[{self.label}] API request failed: {ex}", "error")
                break
            if isinstance(data, dict):
                posts = data.get("posts") or []
            else:
                posts = data or []
            if not isinstance(posts, list) or not posts:
                break
            if randomize:
                posts = list(posts)
                random.shuffle(posts)
            post_count += len(posts)
            for raw in posts:
                if stop_event.is_set() or len(results) >= limit:
                    break
                post = self._post_data(raw)
                post_id = str(post.get("id") or "")
                if not post_id:
                    continue
                title = _safe(post.get("title") or post.get("content") or f"{service} {post_id}", "post")
                post_url = f"{self.root}/{service}/user/{creator}/post/{post_id}"
                files = self._files(post)
                for n, (kind, info) in enumerate(files, 1):
                    if stop_event.is_set() or len(results) >= limit:
                        break
                    item_id = f"{self.id}_{service}_{creator}_{post_id}_{n}"
                    if skip_ids and item_id in skip_ids:
                        continue
                    media_url = self._media_url(info.get("path"))
                    if not media_url:
                        continue
                    ext = _ext(media_url, info.get("name", ""))
                    media_type = _type(ext)
                    if prioritize_images and media_type != "image":
                        # Keep a soft preference; don't throw away non-images if no images arrive.
                        if len(results) and sum(1 for x in results if x.media_type == "image") * 4 >= len(results):
                            continue
                    if getattr(self, "_site_check", False):
                        req = urllib.request.Request(media_url, headers={**HEADERS, "Referer": post_url, "Range": "bytes=0-10485759"})
                        try:
                            with urllib.request.urlopen(req, timeout=8) as probe:
                                status = getattr(probe, "status", None) or probe.getcode()
                                probe.read(10 * 1024 * 1024)
                            if status not in (200, 206):
                                raise OSError(f"HTTP {status}")
                        except Exception as ex:
                            log(f"   -> media probe failed {post_id}/{n}: {ex}", "warning")
                            # A site check only needs one working media URL. Do
                            # not walk every attachment when the first one is
                            # unreachable.
                            break
                        results.append(MediaItem(
                            file_path="", caption=title, media_type=media_type,
                            source_label=f"{self.label}: {service}/{creator}",
                            post_id=item_id, source_type=self.id, attribution=post_url,
                            extra={"service": service, "creator": creator, "post_id": post_id,
                                   "file_kind": kind, "original_url": media_url, "site_check": True},
                        ))
                        break
                    try:
                        content = self._request(media_url, timeout=45, referer=post_url)
                    except Exception as ex:
                        log(f"   -> failed {post_id}/{n}: {ex}", "warning")
                        continue
                    if not content:
                        continue
                    digest = hashlib.md5(content).hexdigest()
                    if digest in self.seen_hashes:
                        continue
                    self.seen_hashes.add(digest)
                    filename = f"{title}_{post_id}_{digest[:8]}{ext}"
                    path = os.path.join(dest_dir, filename)
                    try:
                        with open(path, "wb") as fh:
                            fh.write(content)
                    except OSError as ex:
                        log(f"   -> failed to save {filename}: {ex}", "warning")
                        continue
                    item = MediaItem(
                        file_path=path, caption=title, media_type=media_type,
                        source_label=f"{self.label}: {service}/{creator}",
                        post_id=item_id, source_type=self.id, attribution=post_url,
                        extra={"service": service, "creator": creator, "post_id": post_id,
                               "file_kind": kind, "original_url": media_url},
                    )
                    results.append(item)
                    if item_cb:
                        item_cb(item)
                    if early_preview_cb and len(results) == 3:
                        early_preview_cb(list(results))
                        early_preview_cb = None
            if len(posts) < POST_PAGE:
                break
            offset += POST_PAGE
            progress(post_count, post_count + 1, f"Scanning {self.label}")
        progress(len(results), max(1, len(results)), "Done")
        log(f"--- {self.label} {service}/{creator}: {len(results)} item(s) collected ---")
        return results


class KemonoSource(_KemonoFamily):
    id = "kemono"
    label = "Kemono"
    site_name = "kemono"
    root = "https://kemono.cr"
    check_query = "patreon/user/5163822"
    query_hint = "SERVICE/user/CREATOR or Kemono creator URL"


class CoomerSource(_KemonoFamily):
    id = "coomer"
    label = "Coomer"
    site_name = "coomer"
    root = "https://coomer.st"
    check_query = "onlyfans/user/alinity"
    query_hint = "SERVICE/user/CREATOR or Coomer creator URL"

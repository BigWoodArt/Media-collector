"""Fapello public model/post scraper for MediaCollector."""
import hashlib
import html
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from sources.base import Source
from core.media_item import MediaItem

ROOT = "https://fapello.com"
HEADERS = {
    "User-Agent": "MediaCollector/0.1.6 (public-media-source)",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
}
MIN_INTERVAL = 0.8
POST_RE = re.compile(r'''href\s*=\s*[\"\'](?:(https?://(?:www\.)?fapello\.(?:com|su))?)/([^/\"\']+)/(\d+)/?[^\"\']*[\"\']''', re.I)


def _safe(value):
    value = re.sub(r'[\\/*?:"<>|]', "", str(value or ""))
    return re.sub(r"\s+", " ", value).strip()[:90] or "fapello"


def _url(url):
    url = html.unescape(str(url or "")).strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return ROOT + url
    return url


class FapelloSource(Source):
    id = "fapello"
    label = "Fapello"
    category = "Creator archives"
    check_query = "trending"
    query_hint = "model name or Fapello URL"
    default_limit = 20
    has_media_priority = True
    priority_media = "image"
    default_prioritize = False
    order_choices = [
        ("model", "Model / direct", {}),
        ("trending", "Trending", {"sort": "trending"}),
        ("likes", "Top Likes", {"sort": "top-likes"}),
        ("followers", "Top Followers", {"sort": "top-followers"}),
        ("videos", "Videos", {"sort": "videos"}),
        ("popular_videos", "Popular Videos", {"sort": "popular_videos"}),
    ]
    default_order = "model"

    def __init__(self):
        self._last_request = 0.0
        self.seen_hashes = set()

    def _get(self, url, timeout=20, referer=ROOT + "/"):
        delay = MIN_INTERVAL - (time.time() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        self._last_request = time.time()
        h = dict(HEADERS)
        if referer:
            h["Referer"] = referer
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")

    @classmethod
    def suggest(cls, query):
        q = query.strip().strip("/")
        if not q:
            return []
        if q.lower() in {"trending", "top-likes", "top-followers", "videos", "popular_videos"}:
            return [{"value": q.lower(), "label": f"Fapello {q}", "count": None, "nofilter": True}]
        if q.startswith(("http://", "https://")):
            p = urllib.parse.urlparse(q)
            parts = [x for x in p.path.split("/") if x]
            q = parts[0] if parts else ""
        if not q or not re.fullmatch(r"[A-Za-z0-9_.-]+", q):
            return []
        # Fapello does not expose a useful public model-search API.  Like the
        # existing Erome source, offer the exact search term as a no-filter
        # match; the model AJAX endpoint is resolved when the pick runs.
        return [{"value": q, "label": f"Fapello {q}", "count": None, "nofilter": True}]

    @staticmethod
    def _query(query):
        q = query.strip().strip("/")
        if q.startswith(("http://", "https://")):
            p = urllib.parse.urlparse(q)
            parts = [x for x in p.path.split("/") if x]
        else:
            parts = [x for x in q.split("/") if x]
        if parts and parts[0] in {"trending", "top-likes", "top-followers", "videos", "popular_videos"}:
            return "path", parts[0]
        if parts:
            return "model", parts[0]
        raise ValueError("Enter a Fapello model name or listing.")

    @staticmethod
    def _post_urls(page):
        out = []
        seen = set()
        for match in POST_RE.finditer(page):
            host, model, pid = match.groups()
            url = f"{host or ROOT}/{model}/{pid}/"
            if url not in seen:
                seen.add(url)
                out.append(url)
        return out

    @staticmethod
    def _media(page):
        # Same structure used by the current public Fapello extractor: media is
        # inside the uk-align-center block and is exposed through src=.
        block_match = re.search(r'class\s*=\s*["\'][^"\']*uk-align-center[^"\']*["\'][^>]*>(.*?)</div>', page, re.I | re.S)
        block = block_match.group(1) if block_match else page
        vm = re.search(r'<(?:video|source)\b[^>]*?\bsrc\s*=\s*["\']([^"\']+)', block, re.I | re.S)
        if vm:
            return _url(vm.group(1)), "video"
        im = re.search(r'<img\b[^>]*?\bsrc\s*=\s*["\']([^"\']+)', block, re.I | re.S)
        if im:
            return _url(im.group(1)).replace(".md", "").replace(".th", ""), "image"
        sm = re.search(r'\bsrc\s*=\s*["\']([^"\']+)', block, re.I)
        if sm:
            return _url(sm.group(1)).replace(".md", "").replace(".th", ""), "image"
        return "", ""

    @staticmethod
    def _ext(url, media_type):
        ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
        if ext:
            return ext
        return ".mp4" if media_type == "video" else ".jpg"

    def fetch(self, query, limit, sort, time_range, dest_dir, log, progress, stop_event,
              early_preview_cb=None, randomize=False, prioritize_images=False,
              item_cb=None, skip_ids=None):
        os.makedirs(dest_dir, exist_ok=True)
        try:
            kind, value = self._query(query)
        except ValueError as ex:
            log(f"[Fapello] {ex}", "error")
            return []
        if kind == "model" and sort and sort != "model":
            kind, value = "path", sort
        log(f"Fetching Fapello {kind}: {value}...")

        urls = []
        seen = set()
        for page_no in range(1, 1000):
            if stop_event.is_set() or len(urls) >= max(limit * 4, limit):
                break
            if kind == "model":
                ajax = f"{ROOT}/ajax/model/{urllib.parse.quote(value, safe='.-_')}/page-{page_no}/"
            else:
                ajax_path = value
                ajax = f"{ROOT}/ajax/{ajax_path}/page-{page_no}/"
            try:
                page = self._get(ajax)
            except urllib.error.HTTPError as ex:
                if page_no == 1:
                    log(f"[Fapello] HTTP {ex.code}: {ajax}", "error")
                break
            except Exception as ex:
                log(f"[Fapello] page {page_no} failed: {ex}", "warning")
                break
            found = self._post_urls(page)
            if randomize:
                random.shuffle(found)
            before = len(urls)
            for u in found:
                if u not in seen:
                    seen.add(u)
                    urls.append(u)
            if len(urls) == before or not found:
                break
            progress(len(urls), max(limit, len(urls)), "Scanning Fapello")
            if len(found) < 10:
                break

        if randomize:
            random.shuffle(urls)
        results = []
        for n, post_url in enumerate(urls, 1):
            if stop_event.is_set() or len(results) >= limit:
                break
            match = re.search(r"/([^/]+)/([0-9]+)/?$", urllib.parse.urlparse(post_url).path)
            if not match:
                continue
            model, post_id = match.groups()
            item_id = f"fapello_{model}_{post_id}"
            if skip_ids and item_id in skip_ids:
                continue
            try:
                page = self._get(post_url, referer=ROOT + "/")
            except Exception as ex:
                log(f"   -> failed post {post_id}: {ex}", "warning")
                continue
            media_url, media_type = self._media(page)
            if not media_url:
                continue
            wanted = getattr(self, "wanted_types", None)
            if wanted and media_type not in wanted and not getattr(self, "_site_check", False):
                continue                        # not a type you ticked: don't download it
            if prioritize_images and media_type == "video":
                if any(x.media_type == "image" for x in results):
                    continue
            if getattr(self, "_site_check", False):
                req = urllib.request.Request(media_url, headers={**HEADERS, "Referer": post_url, "Range": "bytes=0-10485759"})
                try:
                    with urllib.request.urlopen(req, timeout=8) as r:
                        status = getattr(r, "status", None) or r.getcode()
                        r.read(10 * 1024 * 1024)
                    if status not in (200, 206):
                        raise OSError(f"HTTP {status}")
                except Exception as ex:
                    log(f"   -> media probe failed {post_id}: {ex}", "warning")
                    continue
                results.append(MediaItem(
                    file_path="", caption=model, media_type=media_type,
                    source_label=f"Fapello: {model}", post_id=item_id, source_type="fapello",
                    attribution=post_url, extra={"model": model, "post_id": post_id,
                                                 "original_url": media_url, "site_check": True},
                ))
                break
            try:
                req = urllib.request.Request(media_url, headers={**HEADERS, "Referer": post_url})
                with urllib.request.urlopen(req, timeout=45) as r:
                    data = r.read()
            except Exception as ex:
                log(f"   -> failed media {post_id}: {ex}", "warning")
                continue
            if not data:
                continue
            digest = hashlib.md5(data).hexdigest()
            if digest in self.seen_hashes:
                continue
            self.seen_hashes.add(digest)
            ext = self._ext(media_url, media_type)
            path = os.path.join(dest_dir, f"{_safe(model)}_{post_id}_{digest[:8]}{ext}")
            try:
                with open(path, "wb") as f:
                    f.write(data)
            except OSError as ex:
                log(f"   -> failed to save {post_id}: {ex}", "warning")
                continue
            item = MediaItem(
                file_path=path, caption=model, media_type=media_type,
                source_label=f"Fapello: {model}", post_id=item_id,
                source_type="fapello", attribution=post_url,
                extra={"model": model, "post_id": post_id, "original_url": media_url},
            )
            results.append(item)
            if item_cb:
                item_cb(item)
            if early_preview_cb and len(results) == 3:
                early_preview_cb(list(results))
                early_preview_cb = None
            progress(n, max(1, len(urls)), f"Downloading Fapello ({n}/{len(urls)})")
        progress(len(results), max(1, len(results)), "Done")
        log(f"--- Fapello {value}: {len(results)} item(s) collected ---")
        return results

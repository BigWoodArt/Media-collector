"""Erome: keyword search (erome.com/search?q=); album links are absolute URLs; albums hold <source>/<img data-src> media."""
import os
import re
import time
import hashlib
import urllib.request
import urllib.error
import urllib.parse

from sources.base import Source
from core.media_item import MediaItem

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
MIN_REQUEST_INTERVAL = 1.0
ALBUM_LINK_RE = re.compile(r'href="(https://www\.erome\.com/a/[A-Za-z0-9_-]+)"', re.IGNORECASE)
TITLE_RE = re.compile(r'<meta\s+property="og:title"\s+content="([^"]*)"', re.IGNORECASE)
VIDEO_RE = re.compile(r'<source[^>]+src="([^"]+)"', re.IGNORECASE)
IMG_DATA_SRC_RE = re.compile(
    r'<img[^>]+class="[^"]*img-back[^"]*"[^>]+data-src="([^"]+)"', re.IGNORECASE)
IMG_SRC_FALLBACK_RE = re.compile(
    r'<img[^>]+class="[^"]*img-back[^"]*"[^>]+src="([^"]+)"', re.IGNORECASE)
ORDER_MAP = {"Hot": "", "New": "new"}


class EromeSource(Source):
    id = "erome"
    check_query = "cosplay"
    category = "GIFs & Video"
    label = "Erome"
    query_hint = "keyword or tag (e.g. cosplay)"
    order_choices = [("hot", "Hot", {"sort": "Hot"}), ("new", "New", {"sort": "New"})]
    default_order = "hot"
    has_media_priority = True

    @classmethod
    def suggest(cls, query):
        """The search word, confirmed by loading the first results page (albums found -> listed; none -> not
        listed; page unreachable -> listed unconfirmed). No total is shown: Erome doesn't publish one."""
        q = query.strip()
        if not q:
            return []
        entry = {"value": q, "label": f"Erome {q}", "count": None, "nofilter": True}
        try:
            req = urllib.request.Request(f"https://www.erome.com/search?q={urllib.parse.quote(q)}",
                                         headers=BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as r:
                html = r.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as ex:
            return [] if ex.code == 404 else [entry]
        except Exception:
            return [entry]
        return [entry] if ALBUM_LINK_RE.search(html) else []

    def __init__(self):
        self._last_request = 0.0
        self.seen_hashes = set()

    def _wait(self):
        elapsed = time.time() - self._last_request
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request = time.time()

    def _get_text(self, url, timeout=15):
        """Returns (status, text); raises HTTPError for non-2xx."""
        self._wait()
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            return status, resp.read().decode("utf-8", errors="ignore")

    def _get_bytes(self, url, timeout=30):
        self._wait()
        headers = dict(BROWSER_HEADERS)
        headers["Referer"] = "https://www.erome.com/"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    def _parse_album(self, html):
        m = TITLE_RE.search(html)
        title = (m.group(1).strip() if m else "") or "erome album"
        video_urls = VIDEO_RE.findall(html)
        image_urls = IMG_DATA_SRC_RE.findall(html) or IMG_SRC_FALLBACK_RE.findall(html)
        media = [(u, "video") for u in dict.fromkeys(video_urls)]
        media += [(u, "image") for u in dict.fromkeys(image_urls)]
        return title, media

    def fetch(self, query, limit, sort, time_range, dest_dir, log, progress, stop_event,
              early_preview_cb=None, randomize=False, prioritize_images=False,
              item_cb=None, skip_ids=None):
        tag = query.strip()
        os.makedirs(dest_dir, exist_ok=True)
        order = ORDER_MAP.get(sort or "Hot", "")
        search_url = f"https://www.erome.com/search?q={urllib.parse.quote(tag)}"
        if order:
            search_url += f"&o={order}"
        log(f"Searching Erome for '{tag}' ({sort})...")

        try:
            status, html = self._get_text(search_url)
        except urllib.error.HTTPError as e:
            body_snippet = ""
            try:
                body_snippet = e.read().decode("utf-8", errors="ignore")[:300]
            except Exception:
                pass
            log(f"[Erome] search request failed: HTTP {e.code}. "
                f"Response snippet: {body_snippet!r}", "error")
            return []
        except Exception as ex:
            log(f"[Erome] search request failed: {ex}", "error")
            return []

        album_paths = list(dict.fromkeys(ALBUM_LINK_RE.findall(html)))
        if not album_paths:
            snippet = re.sub(r'\s+', ' ', html).strip()[:300]
            log(f"No Erome results for '{tag}' (HTTP {status}). "
                f"Response snippet: {snippet!r}", "warning")
            return []
        if randomize:
            import random
            random.shuffle(album_paths)
        log(f"Found {len(album_paths)} album(s). Resolving media...")

        results = []
        images_kept = 0
        videos_kept = 0
        total = len(album_paths)
        for idx, path in enumerate(album_paths, start=1):
            if stop_event.is_set():
                log("--- Stopped by user ---", "warning")
                break
            progress(idx, total, "Scanning Erome albums")
            if len(results) >= limit:
                break

            album_url = path
            album_id = path.rstrip("/").rsplit("/", 1)[-1]
            try:
                _, album_html = self._get_text(album_url)
            except Exception as ex:
                log(f"   -> failed to fetch album {album_id}: {ex}", "warning")
                continue

            title, media = self._parse_album(album_html)
            clean_title = re.sub(r'[\\/*?:"<>|]', "", title)[:40].strip() or "erome"

            for i, (media_url, media_type) in enumerate(media):
                if stop_event.is_set() or len(results) >= limit:
                    break
                if (prioritize_images and media_type == "video"
                        and videos_kept * 4 >= images_kept):
                    continue  # soft cap: skip this video, try the next media item
                if skip_ids and f"erome_{album_id}_{i}" in skip_ids:
                    continue

                try:
                    content = self._get_bytes(media_url)
                except Exception as ex:
                    log(f"   -> failed to fetch media in {album_id}: {ex}", "warning")
                    continue

                file_hash = hashlib.md5(content).hexdigest()
                if file_hash in self.seen_hashes:
                    continue
                self.seen_hashes.add(file_hash)

                ext = os.path.splitext(media_url.split("?")[0])[1] or (
                    ".mp4" if media_type == "video" else ".jpg")
                filename = f"{clean_title}_{file_hash[:8]}{ext}"
                dest_path = os.path.join(dest_dir, filename)
                if not os.path.exists(dest_path):
                    try:
                        with open(dest_path, "wb") as f:
                            f.write(content)
                    except Exception as ex:
                        log(f"   -> failed to save media in {album_id}: {ex}", "warning")
                        continue

                if media_type == "video":
                    videos_kept += 1
                else:
                    images_kept += 1
                log(f"[{idx}/{total}] downloaded from '{title}'")
                item = MediaItem(file_path=dest_path, caption=title, media_type=media_type,
                                  source_label=f"Erome: {tag}", post_id=f"erome_{album_id}_{i}",
                                  source_type="erome")
                results.append(item)
                if item_cb is not None:
                    item_cb(results[-1])
                if early_preview_cb is not None and len(results) == 3:
                    early_preview_cb(list(results))
                    early_preview_cb = None

        progress(len(results), max(len(results), 1), "Done")
        log(f"--- Erome '{tag}': {len(results)} item(s) collected ---")
        return results

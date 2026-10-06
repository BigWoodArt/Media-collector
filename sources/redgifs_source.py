"""Redgifs via the public guest API. Search filters by official tag names (tags=Hypno, case matters): a typed word is
resolved through /v2/search/suggest and results are checked against the tag. Image posts are saved as images;
a photo turned into a looping video becomes a JPEG (needs ffmpeg). Prioritize favours videos."""
import os
import re
import time
import json
import random
import hashlib
import urllib.request
import urllib.error
import urllib.parse

from sources.base import Source
from core.media_item import MediaItem
from core.thumbs import is_static_video, extract_still

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
MIN_REQUEST_INTERVAL = 1.5  # polite pacing — no documented anonymous cap like Reddit's
PAGE_SIZE = 80
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
# Valid API orders (not "new"); "score" is what the redgifs.com search page uses.
ORDER_MAP = {"Score": "score", "Trending": "trending", "Latest": "latest", "Top": "top",
             "Top 7 days": "top7", "Top 28 days": "top28"}


class RedgifsSource(Source):
    id = "redgifs"
    check_query = "cute"
    has_media_priority = True
    priority_media = "video"      # results are mostly videos - Prioritize keeps stills rare
    default_prioritize = True
    category = "GIFs & Video"
    order_choices = [
        ("score", "Best match", {"sort": "Score"}),
        ("trending", "Trending", {"sort": "Trending"}),
        ("latest", "Latest", {"sort": "Latest"}),
        ("top_week", "Top this week", {"sort": "Top 7 days"}),
        ("top_month", "Top this month", {"sort": "Top 28 days"}),
        ("top_all", "Top all time", {"sort": "Top"}),
    ]
    default_order = "score"
    order_help = "Best match is what redgifs.com's own search uses. 'Top this month' is the API's top-28-days list."
    label = "Redgifs"
    query_hint = "a Redgifs tag (e.g. Hypno)"

    @classmethod
    def suggest(cls, query):
        """Redgifs' own tag names for a word, with how many clips carry each."""
        q = query.strip().lstrip("#")
        if not q:
            return []
        try:
            inst = cls()
            token = inst._get_token(lambda *a, **k: None)
            if not token:
                return []
            raw = inst._get_text("https://api.redgifs.com/v2/search/suggest?" + urllib.parse.urlencode({"query": q}),
                                 extra_headers={"Authorization": f"Bearer {token}"})
            data = json.loads(raw)
        except Exception:
            return []
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [])
        return [{"value": d["text"], "label": f"Redgifs {d['text']}", "count": d.get("gifs")}
                for d in data if isinstance(d, dict) and d.get("text")]

    def __init__(self):
        self._last_request = 0.0
        self.seen_hashes = set()
        self._token = None

    def _wait(self):
        elapsed = time.time() - self._last_request
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request = time.time()

    def _get_text(self, url, extra_headers=None, timeout=15):
        self._wait()
        headers = dict(BROWSER_HEADERS)
        headers.setdefault("Accept", "application/json")
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")

    def _get_bytes(self, url, referer=None):
        self._wait()
        headers = dict(BROWSER_HEADERS)
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()

    def _get_token(self, log):
        if self._token:
            return self._token
        try:
            raw = self._get_text("https://api.redgifs.com/v2/auth/temporary")
            self._token = json.loads(raw).get("token")
        except Exception as ex:
            log(f"[Redgifs] failed to get guest token: {ex}", "error")
        return self._token

    # ---- keyword -> Redgifs' own tag names
    def _resolve_tags(self, text, token, log):
        """'hypno' -> ['Hypno'].  Comma-separated input means several tags."""
        parts = [p.strip() for p in text.split(",") if p.strip()]
        return [self._resolve_one_tag(p, token, log) for p in parts] or [text.strip().title()]

    def _resolve_one_tag(self, tag, token, log):
        fallback = tag.title()          # what the redgifs client falls back to for unknown words
        try:
            raw = self._get_text("https://api.redgifs.com/v2/search/suggest?"
                                 + urllib.parse.urlencode({"query": tag}),
                                 extra_headers={"Authorization": f"Bearer {token}"})
            data = json.loads(raw)
        except Exception as ex:
            log(f"tag lookup for '{tag}' failed ({ex}); using '{fallback}'")
            return fallback
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [])
        names = [(d["text"], d.get("gifs")) for d in data if isinstance(d, dict) and d.get("text")]
        if not names:
            log(f"Redgifs has no tag suggestions for '{tag}'; using '{fallback}'")
            return fallback
        chosen = next((n for n, _ in names if n.lower() == tag.lower()), names[0][0])
        shown = ", ".join(f"{n} ({c})" if c is not None else n for n, c in names[:6])
        log(f"tag '{tag}' -> '{chosen}'   (Redgifs suggests: {shown})")
        return chosen

    @staticmethod
    def _tag_hits(gifs, terms):
        """(results carrying one of the tags, results that list any tags at all)"""
        wanted = {t.lower() for t in terms}
        listed = hit = 0
        for g in gifs:
            tags = {str(t).lower() for t in (g.get("tags") or [])}
            if tags:
                listed += 1
                hit += bool(wanted & tags)
        return hit, listed

    def fetch(self, query, limit, sort, time_range, dest_dir, log, progress, stop_event,
              early_preview_cb=None, randomize=False, prioritize_images=False,
              item_cb=None, skip_ids=None):
        tag = query.strip().lstrip("#")
        os.makedirs(dest_dir, exist_ok=True)
        token = self._get_token(log)
        if not token:
            log("Could not authenticate with Redgifs (guest token). Aborting.", "error")
            return []

        order = ORDER_MAP.get(sort or "Score", "score")
        log(f"Searching Redgifs for '{tag}' ({sort})...")
        terms = self._resolve_tags(tag, token, log)
        strategy = "tags"            # "tags" = what Redgifs' own client sends; "search_text" = old way, last resort
        filter_on = False

        results, images_kept, videos_kept, sampled = [], 0, 0, False
        page = 1
        scanned = 0
        while len(results) < limit and not stop_event.is_set():
            params = {"type": "g", "order": order, "count": PAGE_SIZE, "page": page}
            if strategy == "tags":
                params["tags"] = ",".join(terms)
            else:
                params["search_text"] = tag
            url = "https://api.redgifs.com/v2/gifs/search?" + urllib.parse.urlencode(params)
            try:
                try:
                    raw = self._get_text(url, extra_headers={"Authorization": f"Bearer {token}"})
                except urllib.error.HTTPError as ex:
                    if ex.code not in (401, 403):
                        raise
                    log("Redgifs guest token was refused - getting a fresh one and retrying once")
                    self._token = None
                    token = self._get_token(log)
                    if not token:
                        raise
                    raw = self._get_text(url, extra_headers={"Authorization": f"Bearer {token}"})
                data = json.loads(raw)
            except Exception as ex:
                said = ""
                if isinstance(ex, urllib.error.HTTPError):
                    try:   # the API says exactly what it didn't like (e.g. valid sort orders)
                        said = " - " + ex.read()[:220].decode("utf-8", "replace")
                    except Exception:
                        pass
                log(f"[Redgifs] search request failed: {ex}{said}", "error")
                break

            gifs = data.get("gifs", [])
            if not gifs:
                if page == 1 and strategy == "tags" and len(terms) > 1:
                    log(f"No results for all of {terms} together - trying just '{terms[0]}'", "warning")
                    terms = terms[:1]
                    continue
                if page == 1:
                    log(f"No Redgifs results for '{tag}' (searched {strategy}={','.join(terms) if strategy == 'tags' else tag!r}).",
                        "warning")
                break
            hit, listed = self._tag_hits(gifs, terms)
            if listed and hit == 0:
                if page == 1 and strategy == "tags":
                    log(f"None of the {listed} results carry the tag {terms} - the tags= filter wasn't "
                        "applied. Trying the older search_text= parameter.", "warning")
                    strategy = "search_text"
                    continue
                log(f"Redgifs results don't match '{tag}' - stopping instead of downloading unrelated "
                    "videos.", "error" if page == 1 else "warning")
                break
            if listed and hit:
                filter_on = True
            if randomize:
                gifs = list(gifs)
                random.shuffle(gifs)

            for gif in gifs:
                if stop_event.is_set() or len(results) >= limit:
                    break
                scanned += 1
                progress(scanned, max(scanned, limit), "Scanning Redgifs")

                gif_id = gif.get("id", "")
                if skip_ids and f"rg_{gif_id}" in skip_ids:
                    continue
                if filter_on:                            # keep the search honest: off-topic results are skipped
                    gtags = {str(t).lower() for t in (gif.get("tags") or [])}
                    if gtags and not ({t.lower() for t in terms} & gtags):
                        continue
                urls = gif.get("urls") or {}
                hd = urls.get("hd") or urls.get("sd") or ""
                hd_ext = os.path.splitext(hd.split("?")[0])[1].lower()
                still_url = ""
                if hd_ext in IMAGE_EXTS:
                    still_url = hd                       # the file itself is an image
                elif str(gif.get("type")) == "2":        # API: an image post whose hd is a video of it
                    still_url = urls.get("poster") or ""
                media_type = "image" if still_url else "video"
                file_url = still_url or hd
                if not file_url:
                    continue
                meta = {"api_type": gif.get("type"), "duration": gif.get("duration"),
                        "has_audio": gif.get("hasAudio"), "url_keys": sorted(urls)}
                if not sampled:
                    sampled = True
                    log(f"API sample: type={meta['api_type']} duration={meta['duration']} "
                        f"hasAudio={meta['has_audio']} url keys={meta['url_keys']}")
                if prioritize_images and media_type == "image" and images_kept * 4 >= videos_kept:
                    continue                             # favouring videos: skip labelled stills up front

                title = (gif.get("title") or "").strip()
                if not title:
                    tags = gif.get("tags") or []
                    title = ", ".join(tags[:6]) if tags else f"{tag} clip"

                clean_title = re.sub(r'[\\/*?:"<>|]', "", title)[:40].strip() or "redgifs"
                try:
                    content = self._get_bytes(file_url, referer="https://www.redgifs.com/")
                except Exception as ex:
                    log(f"   -> failed to fetch {gif_id}: {ex}", "warning")
                    continue

                file_hash = hashlib.md5(content).hexdigest()
                if file_hash in self.seen_hashes:
                    continue
                self.seen_hashes.add(file_hash)

                if media_type == "video":
                    file_ext = ".mp4"
                else:
                    file_ext = os.path.splitext(file_url.split("?")[0])[1].lower() or ".jpg"
                dest_path = os.path.join(dest_dir, f"{clean_title}_{file_hash[:8]}{file_ext}")
                if os.path.exists(dest_path):
                    continue
                try:
                    with open(dest_path, "wb") as f:
                        f.write(content)
                except Exception as ex:
                    log(f"   -> failed to save {gif_id}: {ex}", "warning")
                    continue

                # A photo-loop video becomes the JPEG it really is.
                if media_type == "video" and not gif.get("hasAudio") and is_static_video(dest_path):
                    jpg_path = os.path.splitext(dest_path)[0] + ".jpg"
                    if extract_still(dest_path, jpg_path):
                        os.remove(dest_path)
                        dest_path, media_type, meta["still_detected"] = jpg_path, "image", True
                        if prioritize_images and images_kept * 4 >= videos_kept:
                            os.remove(dest_path)
                            continue

                meta["saved_as"] = os.path.splitext(dest_path)[1]
                if media_type == "video":
                    videos_kept += 1
                else:
                    images_kept += 1
                log(f"[{len(results) + 1}] downloaded {media_type}: {title}")
                item = MediaItem(file_path=dest_path, caption=title, media_type=media_type,
                                  source_label=f"Redgifs: {tag}", post_id=f"rg_{gif_id}",
                                  source_type="redgifs", extra=meta)
                results.append(item)
                if item_cb is not None:
                    item_cb(results[-1])
                if early_preview_cb is not None and len(results) == 3:
                    early_preview_cb(list(results))
                    early_preview_cb = None

            if len(gifs) < PAGE_SIZE:
                break  # last page
            page += 1

        progress(len(results), max(len(results), 1), "Done")
        log(f"--- Redgifs '{tag}': {len(results)} item(s) collected ---")
        return results

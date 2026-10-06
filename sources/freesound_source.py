"""Freesound: official apiv2 (free key); streams the full-length preview; CC attribution goes to CREDITS.txt."""
import os
import re
import time
import json
import urllib.request
import urllib.error
import urllib.parse

from sources.base import Source
from core.media_item import MediaItem

MIN_REQUEST_INTERVAL = 1.0
SORT_MAP = {
    "Relevance": "score",
    "Rating": "rating_desc",
    "Downloads": "downloads_desc",
    "Newest": "created_desc",
}


def _license_label(url):
    if not url:
        return "unknown license"
    parts = [p for p in url.rstrip("/").split("/") if p]
    if len(parts) >= 2:
        kind, version = parts[-2], parts[-1]
        if kind == "zero":
            return f"CC0 {version}"
        return f"CC {kind.upper()} {version}"
    return url


class FreesoundSource(Source):
    id = "freesound"
    check_query = "rain"
    category = "Audio"
    order_choices = [
        ("relevance", "Relevance", {"sort": "Relevance"}),
        ("downloads", "Most downloaded", {"sort": "Downloads"}),
        ("rating", "Highest rated", {"sort": "Rating"}),
        ("newest", "Newest", {"sort": "Newest"}),
    ]
    default_order = "relevance"
    label = "Freesound"
    query_hint = "tag or keyword (e.g. rain)"
    default_limit = 5

    def __init__(self, api_key=""):
        self.api_key = api_key
        self._last_request = 0.0

    def _wait(self):
        elapsed = time.time() - self._last_request
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request = time.time()

    def _get_json(self, url, timeout=15):
        self._wait()
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))

    def _get_bytes(self, url, timeout=30):
        self._wait()
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    def fetch(self, query, limit, sort, time_range, dest_dir, log, progress, stop_event,
              early_preview_cb=None, randomize=False, prioritize_images=False,
              item_cb=None, skip_ids=None):
        if not self.api_key:
            log("No Freesound API key set (Options tab) — get a free one at "
                "freesound.org/apiv2/apply/. Aborting.", "error")
            return []

        os.makedirs(dest_dir, exist_ok=True)
        sort_param = SORT_MAP.get(sort or "Relevance", "score")
        log(f"Searching Freesound for '{query}' ({sort})...")

        results = []
        page = 1
        scanned = 0
        while len(results) < limit and not stop_event.is_set():
            params = {
                "query": query, "token": self.api_key, "sort": sort_param,
                "page_size": 150, "page": page,
                "fields": "id,name,tags,username,license,previews",
            }
            url = "https://freesound.org/apiv2/search/text/?" + urllib.parse.urlencode(params)
            try:
                data = self._get_json(url)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    log("Freesound rejected the API key (401 Unauthorized). "
                        "Double-check it in the Pack Info panel.", "error")
                else:
                    log(f"[Freesound] search request failed: HTTP {e.code}", "error")
                break
            except Exception as ex:
                log(f"[Freesound] search request failed: {ex}", "error")
                break

            sounds = data.get("results", [])
            if not sounds:
                if page == 1:
                    log(f"No Freesound results for '{query}'.", "warning")
                break
            if randomize:
                import random
                sounds = list(sounds)
                random.shuffle(sounds)

            for sound in sounds:
                if stop_event.is_set() or len(results) >= limit:
                    break
                scanned += 1
                progress(scanned, max(scanned, limit), "Scanning Freesound")

                if skip_ids and f"fs_{sound.get('id', '')}" in skip_ids:
                    continue
                previews = sound.get("previews", {})
                audio_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
                if not audio_url:
                    continue

                name = (sound.get("name") or "").strip() or "freesound clip"
                username = sound.get("username", "")
                license_url = sound.get("license", "")
                sound_id = sound.get("id", "")

                clean_name = re.sub(r'[\\/*?:"<>|]', "", name)[:40].strip() or "freesound"
                filename = f"{clean_name}_{sound_id}.mp3"
                dest_path = os.path.join(dest_dir, filename)
                if not os.path.exists(dest_path):
                    try:
                        content = self._get_bytes(audio_url)
                        with open(dest_path, "wb") as f:
                            f.write(content)
                    except Exception as ex:
                        log(f"   -> failed to download '{name}': {ex}", "warning")
                        continue

                log(f"[{len(results) + 1}] downloaded: {name}")
                item = MediaItem(
                    file_path=dest_path, caption=name, media_type="audio",
                    source_label=f"Freesound: {query}", post_id=f"fs_{sound_id}",
                    source_type="freesound",
                    attribution=f"by {username} on Freesound — {_license_label(license_url)} "
                                f"({license_url})" if username else "")
                results.append(item)
                if item_cb is not None:
                    item_cb(results[-1])
                if early_preview_cb is not None and len(results) == 3:
                    early_preview_cb(list(results))
                    early_preview_cb = None

            if not data.get("next"):
                break
            page += 1

        progress(len(results), max(len(results), 1), "Done")
        log(f"--- Freesound '{query}': {len(results)} item(s) collected ---")
        return results

"""Soundgasm: one creator's upload catalog (no site search); Reddit posts link here too."""
import os
import re
import time
import random
import hashlib
import urllib.request
import urllib.error

from sources.base import Source
from core.media_item import MediaItem

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
MIN_REQUEST_INTERVAL = 1.0  # polite pacing — no documented rate limit
M4A_RE = re.compile(r'(https://(?:media\.)?soundgasm\.net/sounds/[^"\'\s]+\.m4a)')
ENTRY_RE = re.compile(
    r'<a\s+href="(https?://soundgasm\.net/u/[^/"]+/[^"]+)"[^>]*>([^<]*)</a>')


class SoundgasmSource(Source):
    id = "soundgasm"
    check_query = "GateOfIvory"
    category = "Audio"
    label = "Soundgasm"
    query_hint = "paste Creator Name here"
    default_limit = 5
    default_randomize = True   # no search here: newest-N every time would be dull

    def __init__(self):
        self._last_request = 0.0
        self.seen_hashes = set()

    def _wait(self):
        elapsed = time.time() - self._last_request
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request = time.time()

    def _get_text(self, url, timeout=15):
        self._wait()
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")

    def _get_bytes(self, url, timeout=30):
        self._wait()
        headers = dict(BROWSER_HEADERS)
        headers["Referer"] = "https://soundgasm.net/"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    def fetch(self, query, limit, sort, time_range, dest_dir, log, progress, stop_event,
              early_preview_cb=None, randomize=False, prioritize_images=False,
              item_cb=None, skip_ids=None):
        username = query.strip().lstrip("@")
        os.makedirs(dest_dir, exist_ok=True)
        profile_url = f"https://soundgasm.net/u/{username}"
        log(f"Fetching Soundgasm profile for {username}...")
        try:
            html = self._get_text(profile_url)
        except Exception as ex:
            log(f"[Soundgasm] failed to fetch profile: {ex}", "error")
            return []

        entries = ENTRY_RE.findall(html)
        if not entries:
            log(f"No audio entries found for '{username}' — check the username.", "warning")
            return []
        if randomize:
            entries = list(entries)
            random.shuffle(entries)
        log(f"Found {len(entries)} upload(s). Resolving audio files...")

        results = []
        total = len(entries)
        for idx, (page_url, title) in enumerate(entries, start=1):
            if stop_event.is_set():
                log("--- Stopped by user ---", "warning")
                break
            progress(idx, total, "Scanning Soundgasm")
            if len(results) >= limit:
                break

            title = title.strip() or "soundgasm audio"
            if skip_ids and f"sg_{username}_{page_url.rstrip('/').split('/')[-1]}" in skip_ids:
                continue
            try:
                page_html = self._get_text(page_url)
            except Exception as ex:
                log(f"   -> failed to fetch page: {ex}", "warning")
                continue
            m = M4A_RE.search(page_html)
            if not m:
                log(f"[{idx}/{total}] no audio file found: {title}", "warning")
                continue
            audio_url = m.group(1)

            try:
                content = self._get_bytes(audio_url)
            except Exception as ex:
                log(f"   -> failed to download: {ex}", "warning")
                continue

            file_hash = hashlib.md5(content).hexdigest()
            if file_hash in self.seen_hashes:
                continue
            self.seen_hashes.add(file_hash)

            clean_title = re.sub(r'[\\/*?:"<>|]', "", title)[:40].strip() or "soundgasm"
            filename = f"{clean_title}_{file_hash[:8]}.m4a"
            dest_path = os.path.join(dest_dir, filename)
            if os.path.exists(dest_path):
                continue
            try:
                with open(dest_path, "wb") as f:
                    f.write(content)
            except Exception as ex:
                log(f"   -> failed to save: {ex}", "warning")
                continue

            log(f"[{idx}/{total}] downloaded: {title}")
            slug = page_url.rstrip("/").split("/")[-1]
            item = MediaItem(file_path=dest_path, caption=title, media_type="audio",
                              source_label=f"Soundgasm: {username}",
                              post_id=f"sg_{username}_{slug}", source_type="soundgasm")
            results.append(item)
            if item_cb is not None:
                item_cb(results[-1])
            if early_preview_cb is not None and len(results) == 3:
                early_preview_cb(list(results))
                early_preview_cb = None

        progress(len(results), max(len(results), 1), "Done")
        log(f"--- Soundgasm '{username}': {len(results)} item(s) collected ---")
        return results

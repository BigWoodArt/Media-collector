"""Reddit via RSS (no API key); v.redd.it audio is merged with ffmpeg."""
import os
import re
import json
import time
import random
import hashlib
import subprocess
import shutil
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

from sources.base import Source
from core.media_item import MediaItem
from core.winproc import quiet

ATOM_NS = "{http://www.w3.org/2005/Atom}"
MIN_REQUEST_INTERVAL = 6.5  # keeps us under Reddit's ~10 req/min anonymous cap

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


class RateLimiter:
    def __init__(self, min_interval=MIN_REQUEST_INTERVAL):
        self.min_interval = min_interval
        self.last = 0.0

    def wait(self):
        elapsed = time.time() - self.last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last = time.time()


class RedditSource(Source):
    id = "reddit"
    check_query = "aww"
    category = "Reddit"
    supports_quality = True

    @classmethod
    def suggest(cls, query):
        import json, urllib.parse, urllib.request
        qs = urllib.parse.urlencode({"q": query.strip(), "limit": 8, "include_over_18": "on", "sort": "relevance"})
        try:
            req = urllib.request.Request(f"https://www.reddit.com/subreddits/search.json?{qs}",
                                         headers={"User-Agent": "MediaCollector/0.2"})
            with urllib.request.urlopen(req, timeout=8) as r:
                kids = json.loads(r.read().decode("utf-8", "replace"))["data"]["children"]
        except Exception:
            return []
        return [{"value": k["data"]["display_name"], "label": f"Reddit r/{k['data']['display_name']}",
                 "count": k["data"].get("subscribers")} for k in kids if k.get("data")]

    @classmethod
    def resolve_quality(cls, quality):
        return {"Any": {"sort": "New", "time_range": "month"},
                "Good": {"sort": "Top", "time_range": "month"},
                "Best": {"sort": "Top", "time_range": "year"}}.get(quality, {})
    label = "Reddit"
    query_hint = "subreddit (e.g. cats)"
    has_sort = True
    has_time = True
    sort_options = ["Hot", "New", "Rising", "Top", "Controversial"]
    time_options = ["hour", "day", "week", "month", "year", "all"]
    default_sort = "New"
    has_media_priority = True

    def __init__(self):
        self.rate_limiter = RateLimiter()
        self.ffmpeg_available = shutil.which("ffmpeg") is not None
        self._ffmpeg_warned = False
        self.seen_hashes = set()

    # ---------- networking ----------
    def http_get(self, url, log, retries=2):
        for attempt in range(1, retries + 1):
            self.rate_limiter.wait()
            req = urllib.request.Request(url, headers=BROWSER_HEADERS)
            try:
                with urllib.request.urlopen(req, timeout=15) as response:
                    return response.read().decode("utf-8", errors="ignore")
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < retries:
                    log("[HTTP 429] Rate limited by Reddit, waiting 60s...", "warning")
                    time.sleep(60)
                    continue
                log(f"[HTTP Error {e.code}] {e.reason} -> {url}", "error")
                return None
            except Exception as e:
                if attempt < retries:
                    log(f"[Connection Error] {str(e)} - retrying...", "warning")
                    time.sleep(2)
                    continue
                log(f"[Connection Error]: {str(e)}", "error")
                return None
        return None

    def http_get_bytes(self, url, referer=None):
        self.rate_limiter.wait()
        headers = dict(BROWSER_HEADERS)
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.read()

    def _http_get_text(self, url, extra_headers=None, timeout=15):
        self.rate_limiter.wait()
        headers = dict(BROWSER_HEADERS)
        headers.setdefault("Accept", "application/json")
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")

    # ---------- feed ----------
    def build_rss_url(self, sub, sort, time_range):
        base = f"https://www.reddit.com/r/{sub}"
        if sort == "Hot":
            return f"{base}/.rss?limit=100"
        if sort == "Rising":
            return f"{base}/rising/.rss?limit=100"
        if sort == "Top":
            return f"{base}/top/.rss?t={time_range}&limit=100"
        if sort == "Controversial":
            return f"{base}/controversial/.rss?t={time_range}&limit=100"
        return f"{base}/new/.rss?limit=100"

    def parse_feed(self, xml_text, log):
        entries = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            log(f"[Feed Parse Error]: {str(e)}", "error")
            return entries
        for entry in root.findall(f"{ATOM_NS}entry"):
            title_el = entry.find(f"{ATOM_NS}title")
            link_el = entry.find(f"{ATOM_NS}link")
            content_el = entry.find(f"{ATOM_NS}content")
            title = title_el.text if title_el is not None else "media_file"
            link = link_el.get("href") if link_el is not None else None
            content_html = content_el.text if content_el is not None else ""
            if link:
                entries.append({"title": title, "link": link, "content_html": content_html or ""})
        return entries

    # ---------- candidate resolution ----------
    @staticmethod
    def extract_submission_link(content_html):
        if not content_html:
            return None
        m = re.search(r'href="([^"]+)">\s*(?:\[link\]|&#91;link&#93;)',
                      content_html, re.IGNORECASE)
        if not m:
            return None
        return m.group(1).replace("&amp;", "&")

    @staticmethod
    def upgrade_to_source_resolution(url):
        # Exact hostname match: a substring test would mangle external-preview.redd.it.
        host = urllib.parse.urlparse(url).hostname or ""
        if host == "preview.redd.it":
            return url.split("?")[0].replace("preview.redd.it", "i.redd.it")
        return url

    @staticmethod
    def extract_thumbnail_from_content(content_html):
        if not content_html:
            return None
        m = re.search(r'<img[^>]+src="([^"]+)"', content_html)
        if not m:
            return None
        url = m.group(1).replace("&amp;", "&")
        ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".gif"):
            ext = ".jpg"
        return (url, ext)

    def resolve_redgifs(self, redgifs_url, log):
        m = re.search(r"redgifs\.com/(?:watch|ifr)/([A-Za-z0-9]+)",
                       redgifs_url, re.IGNORECASE)
        if not m:
            return None
        gif_id = m.group(1).lower()
        try:
            token_raw = self._http_get_text("https://api.redgifs.com/v2/auth/temporary")
            token = json.loads(token_raw).get("token")
            if not token:
                return None
            data_raw = self._http_get_text(
                f"https://api.redgifs.com/v2/gifs/{gif_id}",
                extra_headers={"Authorization": f"Bearer {token}"})
            data = json.loads(data_raw)
            urls = data.get("gif", {}).get("urls", {})
            return urls.get("hd") or urls.get("sd")
        except Exception as ex:
            log(f"   -> redgifs API error: {ex}", "warning")
            return None

    def resolve_soundgasm(self, soundgasm_url, log):
        """Pull the direct .m4a URL out of a Soundgasm page."""
        try:
            html = self._http_get_text(soundgasm_url)
            m = re.search(r'(https://(?:media\.)?soundgasm\.net/sounds/[^"\'\s]+\.m4a)', html)
            return m.group(1) if m else None
        except Exception as ex:
            log(f"   -> soundgasm resolve error: {ex}", "warning")
            return None

    def build_candidates(self, entry):
        content_html = entry.get("content_html", "")
        candidates = []
        submission_url = self.extract_submission_link(content_html)
        if submission_url and submission_url != entry.get("link", ""):
            low = submission_url.lower().split("?")[0]
            if any(low.endswith(x) for x in [".jpg", ".jpeg", ".png", ".gif"]):
                candidates.append((submission_url, os.path.splitext(low)[1],
                                    "direct submission link", "image"))
            elif low.endswith(".gifv"):
                candidates.append((submission_url[:-5] + ".mp4", ".mp4",
                                    "gifv link upgraded to mp4", "video"))
            elif "v.redd.it" in submission_url:
                m = re.search(r"v\.redd\.it/([A-Za-z0-9]+)", submission_url)
                if m:
                    vid_id = m.group(1)
                    for res in ("1080", "720", "480", "360", "240"):
                        candidates.append((
                            f"https://v.redd.it/{vid_id}/DASH_{res}.mp4", ".mp4",
                            f"v.redd.it DASH_{res}", "video"))
            elif "redgifs.com" in submission_url.lower():
                redgifs_video = self.resolve_redgifs(submission_url, lambda *_: None)
                if redgifs_video:
                    candidates.append((redgifs_video, ".mp4", "redgifs API", "video"))
            elif "soundgasm.net" in submission_url.lower():
                audio_url = self.resolve_soundgasm(submission_url, lambda *_: None)
                if audio_url:
                    candidates.append((audio_url, ".m4a", "soundgasm resolved", "audio"))

        if not ("v.redd.it" in (submission_url or "")):
            thumb = self.extract_thumbnail_from_content(content_html)
            if thumb:
                orig_url, ext = thumb
                full_url = self.upgrade_to_source_resolution(orig_url)
                if full_url != orig_url:
                    candidates.append((full_url, ext, "RSS image upgraded to source resolution", "image"))
                candidates.append((orig_url, ext, "RSS preview image (source unavailable)", "image"))
        return candidates

    def download_one(self, media_url, ext, clean_title, dest_dir, log):
        low = media_url.lower()
        if "redgifs" in low:
            referer = "https://www.redgifs.com/"
        elif "v.redd.it" in low:
            # v.redd.it rejects requests without a Referer (403).
            referer = "https://www.reddit.com/"
        else:
            referer = None
        try:
            content = self.http_get_bytes(media_url, referer=referer)
        except Exception as ex:
            log(f"   -> failed to fetch file: {str(ex)} [{media_url}]", "warning")
            return "fail", None

        file_hash = hashlib.md5(content).hexdigest()
        if file_hash in self.seen_hashes:
            log("   -> duplicate content, skipped")
            return "dupe", None
        self.seen_hashes.add(file_hash)

        filename = f"{clean_title}_{file_hash[:8]}{ext}"
        dest_path = os.path.join(dest_dir, filename)
        if os.path.exists(dest_path):
            return "dupe", None
        try:
            with open(dest_path, "wb") as f:
                f.write(content)
            return "ok", dest_path
        except Exception as ex:
            log(f"   -> failed to save file: {str(ex)}", "warning")
            return "fail", None

    def try_mux_audio(self, video_url, video_path, log):
        m = re.search(r"v\.redd\.it/([A-Za-z0-9]+)/", video_url)
        if not m or video_path is None:
            return
        vid_id = m.group(1)

        audio_bytes = None
        for a_name in ("DASH_audio.mp3", "DASH_AUDIO_128.mp3", "DASH_audio_128.mp3"):
            try:
                audio_bytes = self.http_get_bytes(f"https://v.redd.it/{vid_id}/{a_name}",
                                                    referer="https://www.reddit.com/")
                if audio_bytes:
                    break
            except Exception:
                continue
        if not audio_bytes:
            return
        if not self.ffmpeg_available:
            if not self._ffmpeg_warned:
                log("   -> ffmpeg not found on PATH; install it to keep audio. "
                    "Video kept silent.", "warning")
                self._ffmpeg_warned = True
            return

        audio_path = video_path + ".audio.mp3"
        muxed_path = video_path + ".muxed.mp4"
        try:
            with open(audio_path, "wb") as f:
                f.write(audio_bytes)
            subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-i", video_path, "-i", audio_path,
                 "-c", "copy", "-map", "0:v:0", "-map", "1:a:0", "-shortest", muxed_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=True, **quiet())
            os.remove(video_path)
            os.rename(muxed_path, video_path)
            log("   -> audio muxed successfully")
        except Exception as ex:
            log(f"   -> audio mux failed ({ex}); video kept silent", "warning")
        finally:
            for p in (audio_path, muxed_path):
                if p != video_path and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    # ---------- plugin entrypoint ----------
    def fetch(self, query, limit, sort, time_range, dest_dir, log, progress, stop_event,
              early_preview_cb=None, randomize=False, prioritize_images=False,
              item_cb=None, skip_ids=None):
        sub = query.strip().replace("r/", "")
        os.makedirs(dest_dir, exist_ok=True)
        rss_url = self.build_rss_url(sub, sort or "New", time_range or "month")
        log(f"Fetching RSS feed for r/{sub} ({sort})...")
        xml_text = self.http_get(rss_url, log)
        if xml_text is None:
            log("Could not retrieve subreddit feed. Aborting.", "error")
            return []

        entries = self.parse_feed(xml_text, log)
        if not entries:
            log("No posts found, subreddit is private, or feed format changed.", "error")
            return []
        if randomize:
            random.shuffle(entries)

        log(f"Found {len(entries)} posts. Resolving media "
            f"(~{MIN_REQUEST_INTERVAL:.1f}s between requests)...")
        results = []
        images_kept = 0
        videos_kept = 0
        total = len(entries)
        for idx, entry in enumerate(entries, start=1):
            if stop_event.is_set():
                log("--- Stopped by user ---", "warning")
                break
            progress(idx, total, "Scanning posts")
            if len(results) >= limit:
                break

            title = entry["title"]
            clean_title = re.sub(r'[\\/*?:"<>|]', "", title)[:40].strip()
            post_id_match = re.search(r"/comments/([a-z0-9]+)/", entry.get("link", ""), re.IGNORECASE)
            post_id = post_id_match.group(1).lower() if post_id_match else ""
            if skip_ids and post_id and post_id in skip_ids:
                continue  # already collected by an earlier request

            candidates = self.build_candidates(entry)
            # A gifv/redgifs/v.redd.it post's later candidates are often
            # Skip the whole post, not just the video: its thumbnail fallback gave blurry "images".
            is_video_post = bool(candidates) and candidates[0][3] == "video"
            if prioritize_images and is_video_post and videos_kept * 4 >= images_kept:
                log(f"[{idx}/{total}] skipped (prioritizing images): {clean_title}")
                continue

            result, dest_path, media_type = "fail", None, "image"
            for url, ext, cand_label, cand_type in candidates:
                if stop_event.is_set():
                    break
                result, dest_path = self.download_one(url, ext, clean_title, dest_dir, log)
                if result in ("ok", "dupe"):
                    media_type = cand_type
                    if result == "ok" and cand_label.startswith("v.redd.it DASH_"):
                        self.try_mux_audio(url, dest_path, log)
                    break

            if result == "ok":
                if media_type == "video":
                    videos_kept += 1
                else:
                    images_kept += 1
                log(f"[{idx}/{total}] downloaded: {clean_title}")
                results.append(MediaItem(
                    file_path=dest_path, caption=title, media_type=media_type,
                    source_label=f"r/{sub} via Reddit RSS", post_id=post_id,
                    source_type="reddit"))
                if item_cb is not None:
                    item_cb(results[-1])
                if early_preview_cb is not None and len(results) == 3:
                    early_preview_cb(list(results))
                    early_preview_cb = None  # fire exactly once
            elif result == "dupe":
                pass
            else:
                log(f"[{idx}/{total}] no usable media: {clean_title}")

        progress(total, total, "Done")
        log(f"--- r/{sub}: {len(results)} item(s) collected ---")
        return results

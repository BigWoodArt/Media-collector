"""Shared code for Gelbooru-style boards (dapi API): tags are the site's own; Quality appends score:>=N.
Per-site settings are class attributes. XML replies are parsed, a missing file_url is rebuilt from directory+image,
and when the API refuses the website pages are used (list -> post ids, post -> original file URL)."""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from sources.base import Source
from core.media_item import MediaItem
from core.safety import is_blocked, query_blocked

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
MIN_REQUEST_INTERVAL = 1.0
VIDEO_EXTS = (".mp4", ".webm")
_EXT = r"(?:jpe?g|png|gif|webp|webm|mp4)"
# Original-file URL shapes, most specific first.
FILE_URL_RES = (
    re.compile(rf"""(?:https?:)?//[^/"'\s<>?]+/+images/[0-9a-f]{{2}}/[0-9a-f]{{2}}/[0-9a-f]{{32}}\.{_EXT}""", re.I),
    re.compile(rf"""(?:https?:)?//[^/"'\s<>?]+/+images/\d+/[0-9a-f]{{32,40}}\.{_EXT}""", re.I),
)
LIST_ID_RES = (re.compile(r'\bid="p(\d+)"'),
               re.compile(r"[?&;]s=view(?:&amp;|&)id=(\d+)"))


class BadReply(ValueError):
    """The API answered, but not with posts. .snippet is what it actually said."""
    def __init__(self, message, snippet=""):
        super().__init__(message)
        self.snippet = snippet


class BooruFamilySource(Source):
    category = "Image boards"
    supports_quality = True
    has_sort = False
    has_media_priority = True
    query_hint = "tags (e.g. cat_ears solo)"

    base_url = ""            # API host
    site_url = ""            # public site (Referer, rebuilt URLs); default base_url
    prefix = ""              # post_id prefix, unique per site
    page_size = 100
    quality_scores = {"Good": 10, "Best": 50}   # min score per tier
    api_key_helps = False    # suggest an API key + user ID if all else fails
    html_fallback = True     # use the site's web pages when the API refuses
    # API use: auto (fall back to pages), key (needs key + user ID), off
    api_policy = "auto"

    def __init__(self, api_key="", user_id=""):
        self.api_key, self.user_id = api_key, user_id
        self._last_request = 0.0
        self.seen_hashes = set()
        self._mode = "dapi"          # dapi -> html (web pages)
        self._html_offset = 0
        self._page_len = 0
        self._why_html = ""
        if self.api_policy == "off":
            self._mode, self._why_html = "html", "its API is switched off"
        elif self.api_policy == "key" and not (api_key and user_id):
            self._mode, self._why_html = "html", "its API needs an API key + user ID (both) - none set"

    @classmethod
    def resolve_quality(cls, quality):
        n = cls.quality_scores.get(quality)
        return {"query_suffix": f"score:>={n}"} if n else {}

    # ---- http
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
        headers["Referer"] = (self.site_url or self.base_url) + "/"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    # ---- api
    def _dapi_url(self, tags, page):
        params = {"page": "dapi", "s": "post", "q": "index", "json": "1",
                  "tags": tags, "limit": self.page_size, "pid": page}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.user_id:
            params["user_id"] = self.user_id
        return f"{self.base_url}/index.php?{urllib.parse.urlencode(params)}"

    @staticmethod
    def _extract_posts(raw):
        text = raw.strip()
        if not text:
            return []
        snippet = re.sub(r"\s+", " ", text[:160])
        if text.startswith("<"):
            if re.match(r"<!doctype html|<html", text, re.I):
                raise BadReply("got a web page instead of data", snippet)
            try:                       # some boards answer XML, including for "no results"
                root = ET.fromstring(text)
            except ET.ParseError:
                raise BadReply("unreadable XML reply", snippet)
            if root.tag == "response" and root.get("success") == "false":   # e.g. "API offline"
                raise BadReply(root.get("reason") or "the API reported an error", snippet)
            return [dict(el.attrib) for el in root.iter("post")]
        try:
            data = json.loads(text)
        except ValueError:
            raise BadReply("reply wasn't JSON", snippet)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            posts = data.get("post") or data.get("posts")
            if posts is not None:
                return posts if isinstance(posts, list) else [posts]
            if "@attributes" in data:               # valid "0 results"
                return []
            if data.get("success") is False or data.get("message") or data.get("error"):
                raise BadReply(str(data.get("message") or data.get("error") or "API error"), snippet)
            return []
        # a bare string/number (Rule34's "Missing authentication...")
        raise BadReply(str(data) if isinstance(data, str) else "unexpected reply", snippet)

    # ---- website fallback
    def _list_url(self, tags):
        params = {"page": "post", "s": "list", "tags": tags, "pid": self._html_offset}
        return f"{self.site_url or self.base_url}/index.php?{urllib.parse.urlencode(params)}"

    def _html_posts(self, tags):
        html = self._get_text(self._list_url(tags))
        ids = []
        for rx in LIST_ID_RES:
            for found in rx.findall(html):
                if found not in ids:
                    ids.append(found)
        if not ids and re.match(r"\s*(?:<!doctype html|<html)", html, re.I) and "Just a moment" in html[:3000]:
            raise BadReply("blocked by a browser check (Cloudflare)", re.sub(r"\s+", " ", html[:160]))
        self._page_len = self._page_len or len(ids)
        self._html_offset += len(ids)
        return [{"id": i, "_lazy": True} for i in ids]

    def _html_file(self, post_id):
        """Post page -> original file URL (None if the page has none)."""
        url = (f"{self.site_url or self.base_url}/index.php?"
               + urllib.parse.urlencode({"page": "post", "s": "view", "id": post_id}))
        html = self._get_text(url)
        for rx in FILE_URL_RES:
            m = rx.search(html)
            if m:
                found = m.group(0)
                return "https:" + found if found.startswith("//") else found
        return None

    def _get_posts(self, tags, page, log=None):
        if self._mode == "html":
            return self._html_posts(tags)
        try:
            return self._extract_posts(self._get_text(self._dapi_url(tags, page)))
        except (urllib.error.HTTPError, ValueError) as ex:
            if not self.html_fallback or page != 0:
                raise
            if log:
                log(f"API refused ({self._explain(ex, hint=False)}) - using {self.label}'s web pages "
                    "instead (slower: two requests per item, but no account needed)", "warning")
            self._mode = "html"
            self._html_offset = 0
            return self._html_posts(tags)

    def _explain(self, ex, hint=True):
        if hint and self.api_key_helps and not self.api_key:
            hint = "; if this keeps failing, an API key + user ID in the Options tab may help"
        else:
            hint = ""
        if isinstance(ex, urllib.error.HTTPError):
            if ex.code in (401, 403):
                try:
                    said = re.sub(r"\s+", " ", ex.read()[:120].decode("utf-8", "replace")).strip()
                except Exception:
                    said = ""
                return f"HTTP {ex.code} - access refused" + (f" ({said!r})" if said else "") + hint
            return f"HTTP {ex.code}"
        if isinstance(ex, BadReply):
            return f"{ex}: {ex.snippet!r}{hint}" if ex.snippet else f"{ex}{hint}"
        if isinstance(ex, ValueError):
            return f"reply wasn't JSON{hint}"
        return str(ex)

    def _file_url(self, post):
        url = post.get("file_url") or ""
        if not url:
            directory, image = post.get("directory"), post.get("image")
            if directory not in (None, "") and image:
                url = f"{self.site_url or self.base_url}/images/{directory}/{image}"
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = (self.site_url or self.base_url) + url
        return url

    # ---- plugin entrypoint
    def fetch(self, query, limit, sort, time_range, dest_dir, log, progress, stop_event,
              early_preview_cb=None, randomize=False, prioritize_images=False,
              item_cb=None, skip_ids=None):
        tags = query.strip()
        os.makedirs(dest_dir, exist_ok=True)
        if query_blocked(tags):
            log(f"[{self.label}] that search asks for material this tool never collects - skipped.", "warning")
            return []
        log(f"Searching {self.label} for '{tags}'...")
        if self._why_html:
            log(f"using {self.label}'s web pages (slower: two requests per item) - {self._why_html}")

        results, images_kept, videos_kept = [], 0, 0
        page, scanned, no_url = 0, 0, 0
        seen_ids = set()      # stops a site that ignores paging and repeats itself
        while len(results) < limit and not stop_event.is_set():
            try:
                posts = self._get_posts(tags, page, log)
            except Exception as ex:
                log(f"[{self.label}] search request failed: {self._explain(ex)}", "error")
                break
            log(f"page {page + 1}: {len(posts)} post(s) via {self._mode}")
            if not posts:
                if page == 0:
                    if self._mode == "html":
                        log(f"The {self.label} web page listed no posts for '{tags}' - either "
                            "nothing matches, or the page layout isn't recognized.", "warning")
                    else:
                        log(f"No {self.label} results for '{tags}' - the site answered but "
                            "listed nothing for those tags.", "warning")
                break
            if randomize:
                import random
                posts = list(posts)
                random.shuffle(posts)

            fresh_on_page = 0
            for post in posts:
                if stop_event.is_set() or len(results) >= limit:
                    break
                scanned += 1
                progress(scanned, max(scanned, limit), f"Scanning {self.label}")
                post_id = post.get("id", "")
                if not post_id or post_id in seen_ids:
                    continue
                seen_ids.add(post_id)
                fresh_on_page += 1
                if skip_ids and f"{self.prefix}{post_id}" in skip_ids:
                    continue
                if is_blocked((post.get("tags") or "").split()):
                    continue
                if post.get("_lazy"):            # website fallback: fetch the post page for its file
                    try:
                        post["file_url"] = self._html_file(post_id)
                    except Exception as ex:
                        log(f"   -> post page {post_id} failed: {self._explain(ex)}", "warning")
                        continue
                file_url = self._file_url(post)
                if not file_url:
                    no_url += 1
                    continue
                ext = os.path.splitext(file_url.split("?")[0])[1].lower() or ".jpg"
                media_type = "video" if ext in VIDEO_EXTS else "image"
                if prioritize_images and media_type == "video" and videos_kept * 4 >= images_kept:
                    continue   # soft cap: skip this post, try the next one

                try:
                    content = self._get_bytes(file_url)
                except Exception as ex:
                    log(f"   -> failed to fetch post {post_id}: {self._explain(ex)}", "warning")
                    continue
                file_hash = hashlib.md5(content).hexdigest()
                if file_hash in self.seen_hashes:
                    continue
                self.seen_hashes.add(file_hash)

                post_tags = (post.get("tags") or "").split()
                title = ", ".join(post_tags[:6]) if post_tags else f"{tags} post"
                clean = re.sub(r'[\\/*?:"<>|]', "", title)[:40].strip() or self.id
                dest_path = os.path.join(dest_dir, f"{clean}_{file_hash[:8]}{ext}")
                if not os.path.exists(dest_path):
                    try:
                        with open(dest_path, "wb") as f:
                            f.write(content)
                    except Exception as ex:
                        log(f"   -> failed to save post {post_id}: {ex}", "warning")
                        continue

                if media_type == "video":
                    videos_kept += 1
                else:
                    images_kept += 1
                log(f"[{len(results) + 1}] downloaded post {post_id}")
                results.append(MediaItem(
                    file_path=dest_path, caption=title, media_type=media_type,
                    source_label=f"{self.label}: {tags}", post_id=f"{self.prefix}{post_id}",
                    source_type=self.id))
                if item_cb is not None:
                    item_cb(results[-1])
                if early_preview_cb is not None and len(results) == 3:
                    early_preview_cb(list(results))
                    early_preview_cb = None

            if len(posts) < (self._page_len or self.page_size):
                break   # last page
            if fresh_on_page == 0:
                log(f"page {page + 1} repeated earlier posts - stopping", "warning")
                break
            page += 1

        if not results and no_url:
            log(f"{no_url} post(s) came back with no file URL - the site's layout may have changed.",
                "warning")
        progress(len(results), max(len(results), 1), "Done")
        log(f"--- {self.label} '{tags}': {len(results)} item(s) collected ---")
        return results

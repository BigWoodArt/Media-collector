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
import threading
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

    img_root = ""               # preview host: <img_root>/thumbnail/data/... still works where the full-size file servers are blocked
    check_timeout = 45.0        # big creator pages are slow; the site check waits longer for these
    root = ""
    site_name = ""
    id = ""
    label = ""
    query_hint = "SERVICE/user/CREATOR or creator URL"

    def __init__(self, base_url=""):
        self._last_request = 0.0
        self.seen_hashes = set()
        base = (base_url or "").strip().rstrip("/")
        if base:                    # the sites rotate domains (.cr/.su/.pro, .st/.su/...): let the user pick a live one
            self.root = base if "://" in base else "https://" + base

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

    API_TIMEOUT = 40.0

    def _json_stoppable(self, url, stop_event):
        """_json() in a helper thread so Stop works and a stuck server can't hang the run forever."""
        box = {}

        def work():
            try:
                box["v"] = self._json(url)
            except BaseException as ex:         # noqa: BLE001 - re-raised below
                box["e"] = ex
        t = threading.Thread(target=work, daemon=True)
        t.start()
        end = time.time() + self.API_TIMEOUT
        while t.is_alive():
            if stop_event.is_set():
                raise InterruptedError("stopped")
            if time.time() > end:
                raise TimeoutError(f"no answer from the API after {self.API_TIMEOUT:.0f}s")
            t.join(0.25)
        if "e" in box:
            raise box["e"]
        return box["v"]

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
        qn = re.sub(r"[^a-z0-9]", "", q)       # "Queen of Milk", "queen_of_milk" and "queenofmilk" all match
        now = time.time()
        cached = CREATOR_CACHE.get(cls.id)
        if cached and now - cached[0] < CREATOR_CACHE_TTL:
            creators = cached[1]
        else:
            try:
                req = urllib.request.Request(cls.root + "/api/v1/creators", headers=HEADERS)
                with urllib.request.urlopen(req, timeout=40) as r:
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
            if not service or not cid:
                continue
            if q not in hay and qn not in re.sub(r"[^a-z0-9]", "", f"{name} {cid}".lower()):
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

    BARE_SERVICES = ("onlyfans", "fansly", "candfans")      # Coomer services a bare username may live on

    @classmethod
    def _profile_state(cls, root, service, creator):
        """-> ("yes", name) | ("no", "") | ("unknown", "").  404 = definitely no such creator on that service."""
        url = f"{root}/api/v1/{service}/user/{urllib.parse.quote(creator, safe='')}/profile"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=10) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            if isinstance(data, dict) and (data.get("id") or data.get("name")):
                return "yes", str(data.get("name") or creator)
            return "no", ""
        except urllib.error.HTTPError as ex:
            return ("no", "") if ex.code == 404 else ("unknown", "")
        except Exception:
            return "unknown", ""

    @classmethod
    def _find_bare(cls, root, name):
        """Look a bare Coomer username up on each service (in parallel). -> (hits [(service, id, display)], any_unknown)."""
        creator = name.strip().lower()
        out = {}

        def one(svc):
            out[svc] = cls._profile_state(root, svc, creator)
        threads = [threading.Thread(target=one, args=(sv,), daemon=True) for sv in cls.BARE_SERVICES]
        for t in threads:
            t.start()
        for t in threads:
            t.join(12)
        hits = [(sv, creator, out[sv][1]) for sv in cls.BARE_SERVICES if out.get(sv, ("unknown",))[0] == "yes"]
        unknown = any(out.get(sv, ("unknown",))[0] == "unknown" for sv in cls.BARE_SERVICES)
        return hits, unknown

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
            hits, unknown = cls._find_bare(cls.root, q)
            if hits:
                return [{"value": f"{sv}/user/{cid}", "label": f"{cls.label} {sv}: {disp}",
                         "count": None, "nofilter": True} for sv, cid, disp in hits]
            if unknown:         # couldn't check (offline/blocked): offer the usual guess rather than nothing
                service, creator = cls._parse_query(q)
                return [{"value": f"{service}/user/{creator}",
                         "label": f"{cls.label} {service}: {creator}", "count": None, "nofilter": True}]
            return cls._creator_matches(q)          # no exact account: partial matches from the creator list
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

    _full_blocked = False
    last_was_preview = False
    _node = ""      # media host prefix that last worked ("n4"), tried first next time

    def _candidates(self, url):
        """Media files are served from numbered nodes (n1..n4.<domain>); the main domain's /data/ path may not be
        reachable. Try the URL as given plus each node, the last working one first."""
        if not url.startswith(self.root + "/"):
            return [url]
        host, tail = urllib.parse.urlparse(self.root).netloc, url[len(self.root):]
        nodes = [f"https://n{i}.{host}{tail}" for i in (1, 2, 3, 4)]
        out = [url] + nodes
        if self._node:
            first = f"https://{self._node}.{host}{tail}"
            out = [first] + [u for u in out if u != first]
        return out

    def _thumb_url(self, media_url):
        path = urllib.parse.urlparse(media_url).path
        if not self.img_root or not path.startswith("/data/") or _type(_ext(media_url)) != "image":
            return ""
        return self.img_root + "/thumbnail" + path

    def _get_media(self, url, referer, probe=False, log=None):
        """-> (bytes, working_url). probe=True only checks that the file starts downloading.
        If no full-size host answers but the preview host does, returns the preview and sets self.last_was_preview."""
        self.last_was_preview = False
        last = OSError("no media host answered")
        thumb = self._thumb_url(url)
        if self._full_blocked and not thumb:
            if log and not getattr(self, "_skip_noted", False):
                self._skip_noted = True
                log(f"[{self.label}] full-size file servers are unreachable from this network: videos can't be "
                    f"downloaded (only the preview of images can)", "warning")
            raise OSError("full-size file servers are unreachable from this network (no preview exists for this file type)")
        if thumb:
            # One quick try at the full-size file (the site redirects to a file server anyway); then the preview.
            cands = ([] if self._full_blocked else [url]) + [thumb]
        else:
            cands = self._candidates(url)
        for cand in cands:
            if self._full_blocked and cand not in (url, thumb):
                continue                    # the main file server is unreachable: n1..n4 are the same story
            try:
                ref = self.root + "/" if cand == thumb else referer
                if probe:
                    req = urllib.request.Request(cand, headers={**HEADERS, "Referer": ref, "Range": "bytes=0-65535"})
                    with urllib.request.urlopen(req, timeout=8) as r:
                        status = getattr(r, "status", None) or r.getcode()
                        r.read(65536)
                    if status not in (200, 206):
                        raise OSError(f"HTTP {status}")
                    data = b""
                else:
                    data = self._request(cand, timeout=15, referer=ref)
            except Exception as ex:
                last = ex
                if cand == url and not isinstance(ex, urllib.error.HTTPError):
                    self._full_blocked = True           # can't connect at all: don't wait on it again this run
                continue
            if cand == thumb:
                self.last_was_preview = True
                self._full_blocked = True           # full-size servers unreachable: go straight to previews from now on
                if not getattr(self, "_preview_noted", False):
                    self._preview_noted = True
                    if log:
                        log(f"[{self.label}] full-size file servers aren't reachable from this network - "
                            f"using the site's (smaller) preview images instead", "warning")
                return data, cand
            host = urllib.parse.urlparse(cand).netloc
            if host.startswith("n") and "." in host and host.split(".", 1)[0][1:].isdigit():
                self._node = host.split(".", 1)[0]
            return data, cand
        raise last

    def _get_media_stoppable(self, url, referer, stop_event, probe=False, log=None, limit=90.0):
        """_get_media() in a helper thread: Stop acts within a second and one file can't hang the run."""
        box = {}

        def work():
            try:
                box["v"] = self._get_media(url, referer, probe=probe, log=log)
            except BaseException as ex:         # noqa: BLE001 - re-raised below
                box["e"] = ex
        t = threading.Thread(target=work, daemon=True)
        t.start()
        end = time.time() + limit
        while t.is_alive():
            if stop_event.is_set():
                raise InterruptedError("stopped")
            if time.time() > end:
                raise TimeoutError(f"file download took longer than {limit:.0f}s")
            t.join(0.25)
        if "e" in box:
            raise box["e"]
        return box["v"]

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
        bare = [x for x in re.split(r"[/]+", re.sub(r"^https?://[^/]+/", "", query.strip())) if x]
        if self.id == "coomer" and len(bare) == 1:
            # A bare name is not necessarily an OnlyFans account: find which service actually has it.
            hits, unknown = self._find_bare(self.root, bare[0])
            if hits:
                service, creator = hits[0][0], hits[0][1]
                log(f"[{self.label}] '{bare[0]}' found on {service}" +
                    (f" (also on {', '.join(h[0] for h in hits[1:])} - use SERVICE/user/NAME for those)" if len(hits) > 1 else ""))
            elif not unknown:
                matches = self._creator_matches(bare[0])        # Fansly etc. use numeric IDs: match by display name
                if matches:
                    service, _, creator = matches[0]["value"].split("/", 2)
                    log(f"[{self.label}] '{bare[0]}' matched {matches[0]['label']}" +
                        (f" (other matches: {', '.join(m['value'] for m in matches[1:4])})" if len(matches) > 1 else ""))
                else:
                    log(f"[{self.label}] no creator named '{bare[0]}'. Use the creator's page address instead "
                        f"(SERVICE/user/ID, e.g. fansly/user/549327668156313600).", "error")
                    return []

        endpoint = f"{self.root}/api/v1/{urllib.parse.quote(service, safe='')}/user/{urllib.parse.quote(creator, safe='')}/posts"
        log(f"[{self.label}] endpoint: {endpoint}?o=0", "debug")
        log(f"Fetching {self.label} {service}/user/{creator}...")
        results = []
        self._full_blocked = False
        offset = 0
        post_count = 0
        while len(results) < limit and not stop_event.is_set():
            url = endpoint + "?" + urllib.parse.urlencode({"o": offset})
            try:
                t_api = time.time()
                log(f"[{self.label}] asking the API for posts (offset {offset})...", "debug")
                data = self._json_stoppable(url, stop_event)
                log(f"[{self.label}] API answered in {time.time() - t_api:.1f}s", "debug")
            except InterruptedError:
                break
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
                    wanted = getattr(self, "wanted_types", None)
                    if wanted and media_type not in wanted and not getattr(self, "_site_check", False):
                        continue                # e.g. only Image ticked: don't even start downloading videos
                    if prioritize_images and media_type != "image":
                        # Keep a soft preference; don't throw away non-images if no images arrive.
                        if len(results) and sum(1 for x in results if x.media_type == "image") * 4 >= len(results):
                            continue
                    if getattr(self, "_site_check", False):
                        try:
                            _, media_url = self._get_media_stoppable(media_url, post_url, stop_event, probe=True, log=log)
                        except InterruptedError:
                            return results
                        except Exception as ex:
                            log(f"[{self.label}] API answers but no media host does ({ex})", "error")
                            return results
                        results.append(MediaItem(
                            file_path="", caption=title, media_type=media_type,
                            source_label=f"{self.label}: {service}/{creator}",
                            post_id=item_id, source_type=self.id, attribution=post_url,
                            extra={"service": service, "creator": creator, "post_id": post_id,
                                   "file_kind": kind, "original_url": media_url, "site_check": True,
                                   "preview": self.last_was_preview},
                        ))
                        break
                    log(f"[{self.label}] downloading file {len(results) + 1}: post {post_id}/{n} ({media_type})", "debug")
                    try:
                        content, media_url = self._get_media_stoppable(media_url, post_url, stop_event, log=log)
                    except InterruptedError:
                        break
                    except Exception as ex:
                        log(f"   -> failed {post_id}/{n}: {ex}", "warning")
                        continue
                    if not content:
                        continue
                    digest = hashlib.md5(content).hexdigest()
                    if digest in self.seen_hashes:
                        continue
                    self.seen_hashes.add(digest)
                    preview = self.last_was_preview
                    filename = f"{title}_{post_id}_{digest[:8]}{'_preview' if preview else ''}{ext}"
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
                               "file_kind": kind, "original_url": media_url, "preview": preview},
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
    img_root = "https://img.kemono.cr"
    check_query = "patreon/user/5163822"
    query_hint = "SERVICE/user/CREATOR or Kemono creator URL"


class CoomerSource(_KemonoFamily):
    id = "coomer"
    label = "Coomer"
    site_name = "coomer"
    root = "https://coomer.st"
    img_root = "https://img.coomer.st"
    check_query = "onlyfans/user/alinity"
    query_hint = "SERVICE/user/CREATOR or Coomer creator URL"

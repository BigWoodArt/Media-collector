"""Redgifs via the public guest API. A typed word goes:
  1. the niches (Redgifs' curated playlists) that really are about it, shared out evenly;
  2. else Redgifs' own tag of that name (tags=Hypno, case matters; checked against each result);
  3. else a text search, keeping only clips whose description or tags hold the word.
Search forms: word | niche:<id> | tag:<Tag> | a,b (several tags). Image posts are saved as images;
a photo turned into a looping video becomes a JPEG (needs ffmpeg). Prioritize favours videos."""
import math
from collections import Counter
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
API = "https://api.redgifs.com"
MIN_NICHE_GIFS = 20        # a niche with fewer clips is not worth a row
MAX_NICHES = 3             # niches pulled from for one typed word
SUGGEST_NICHES = 6
SUGGEST_TAGS = 6
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
# Valid API orders (not "new"); "score" is what the redgifs.com search page uses.
ORDER_MAP = {"Score": "score", "Trending": "trending", "Latest": "latest", "Top": "top",
             "Top 7 days": "top7", "Top 28 days": "top28"}
# gifs/search order -> niche order. The niche API takes only best, hot, latest, oldest ("trending" is refused).
NICHE_ORDER = {"score": "best", "trending": "hot", "latest": "latest", "top": "best", "top7": "hot", "top28": "best"}


def _words_in(gif, word):
    """True if every word of `word` appears as a whole word (or plural) in the clip's description, title or tags."""
    text = " ".join([str(gif.get("description") or ""), str(gif.get("title") or "")]
                    + [str(t) for t in (gif.get("tags") or [])]).lower()
    return all(re.search(r"\b" + re.escape(w) + r"s?\b", text) for w in word.lower().split())


def rank_niches(word, niches):
    """Niches that are really about `word`, best first. The API's niche search is loose (a search for
    'hypnotic' also returns 'Seductive'), so a niche must have the word's stem in its name (best) or its tags."""
    stems = [w[:max(4, len(w) - 3)] for w in word.lower().split() if w]
    scored = []
    for n in niches:
        if not isinstance(n, dict) or not n.get("id") or (n.get("gifs") or 0) < MIN_NICHE_GIFS:
            continue
        name = f"{n['id']} {n.get('name') or ''}".lower()
        tags = " ".join(str(t) for t in (n.get("tags") or [])).lower()
        score = 2 if any(st in name for st in stems) else 1 if any(st in tags for st in stems) else 0
        if score:
            scored.append((score, int(n.get("gifs") or 0), str(n["id"]), str(n.get("name") or n["id"])))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return [{"id": i, "name": nm, "gifs": g} for _, g, i, nm in scored]


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
        """Matching niches (with clip counts), Redgifs' own tags, then the tags most used by clips that mention the word."""
        q = query.strip().lstrip("#")
        if not q:
            return []
        inst = cls()
        log = lambda *a, **k: None
        out = [{"value": f"niche:{n['id']}", "label": f"Redgifs niche: {n['name']}", "count": n["gifs"]}
               for n in inst.find_niches(q, log)[:SUGGEST_NICHES]]
        have = set()
        for name, count in inst._tag_suggestions(q, log):
            have.add(name.lower())
            out.append({"value": f"tag:{name}", "label": f"Redgifs tag: {name}", "count": count})
        tags, total = inst.common_tags(q, log)
        out += [{"value": f"tag:{name}", "label": f"Redgifs tag: {name}  (in {c} of {total} matching clips)", "count": None}
                for name, c in tags if name.lower() not in have]
        return out

    # ---- niche and tag lookups
    def _api(self, path, params, log):
        token = self._get_token(log)
        if not token:
            return None
        raw = self._get_text(f"{API}{path}?" + urllib.parse.urlencode(params),
                             extra_headers={"Authorization": f"Bearer {token}"})
        return json.loads(raw)

    def find_niches(self, word, log):
        """[{'id','name','gifs'}] that are about `word`, best first. Never raises."""
        try:
            data = self._api("/v2/niches", {"query": word, "count": 20, "page": 1}, log)
        except Exception as ex:
            log(f"[Redgifs] niche lookup failed: {ex}", "warning")
            return []
        return rank_niches(word, (data or {}).get("niches", []) if isinstance(data, dict) else [])

    def _tag_suggestions(self, word, log):
        """[(tag, clip count)] from Redgifs' own tag suggestions. Never raises."""
        try:
            data = self._api("/v2/search/suggest", {"query": word}, log)
        except Exception:
            return []
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [])
        return [(d["text"], d.get("gifs")) for d in data or [] if isinstance(d, dict) and d.get("text")][:SUGGEST_TAGS]

    def common_tags(self, word, log):
        """([(tag, uses)], clips counted): the tags most used by clips whose own text holds the word."""
        try:
            data = self._api("/v2/gifs/search", {"type": "g", "query": word, "order": "score", "count": PAGE_SIZE, "page": 1}, log)
        except Exception as ex:
            log(f"[Redgifs] tag lookup failed: {ex}", "warning")
            return [], 0
        gifs = [g for g in (data or {}).get("gifs", []) if isinstance(g, dict) and _words_in(g, word)]
        seen, names = Counter(), {}
        for g in gifs:
            for t in {str(t) for t in (g.get("tags") or []) if str(t).strip()}:
                seen[t.lower()] += 1
                names.setdefault(t.lower(), t)
        top = [(names[k], c) for k, c in seen.most_common(SUGGEST_TAGS * 2) if c >= 2][:SUGGEST_TAGS]
        return top, len(gifs)

    def __init__(self):
        self._last_request = 0.0
        self.seen_hashes = set()
        self.seen_ids = set()
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
        q = (query or "").strip().lstrip("#")
        once = [early_preview_cb]

        def preview(items):                       # the early preview fires once, however many niches are searched
            cb, once[0] = once[0], None
            if cb:
                cb(items)
        rest = (sort, time_range, dest_dir, log, progress, stop_event)
        kw = dict(early_preview_cb=preview if early_preview_cb else None, randomize=randomize,
                  prioritize_images=prioritize_images, item_cb=item_cb, skip_ids=skip_ids)
        low = q.lower()
        if low.startswith("niche:"):
            nid = q[6:].strip()
            return self._fetch_one("niche", nid, limit, *rest, **kw)
        if low.startswith("tag:"):
            return self._fetch_one("tags", q[4:].strip(), limit, *rest, **kw)
        if "," in q or not q:
            return self._fetch_one("tags", q, limit, *rest, **kw)

        niches = self.find_niches(q, log)[:MAX_NICHES]
        if niches:
            log("[Redgifs] niches about '%s': %s" % (q, ", ".join(f"{n['name']} ({n['gifs']})" for n in niches)))
            results, share = [], math.ceil(limit / len(niches))
            for n in niches:
                if stop_event.is_set() or len(results) >= limit:
                    break
                results += self._fetch_one("niche", n["id"], min(share, limit - len(results)), *rest, **kw)
            if results or stop_event.is_set():
                return results
            log(f"[Redgifs] the niches gave nothing; trying the tag '{q}'", "warning")
        results = self._fetch_one("tags", q, limit, *rest, **kw)
        if results or stop_event.is_set():
            return results
        log(f"[Redgifs] no tag '{q}'; searching clip text for the word instead")
        return self._fetch_one("text", q, limit, *rest, **kw)

    def _fetch_one(self, mode, query, limit, sort, time_range, dest_dir, log, progress, stop_event,
                   early_preview_cb=None, randomize=False, prioritize_images=False,
                   item_cb=None, skip_ids=None):
        """One search. mode: "tags" (Redgifs' tag filter), "niche" (one niche's clips) or "text" (free text)."""
        tag = query.strip().lstrip("#")
        os.makedirs(dest_dir, exist_ok=True)
        token = self._get_token(log)
        if not token:
            log("Could not authenticate with Redgifs (guest token). Aborting.", "error")
            return []

        order = ORDER_MAP.get(sort or "Score", "score")
        log(f"Searching Redgifs for '{tag}' ({sort})...")
        terms = self._resolve_tags(tag, token, log) if mode == "tags" else [tag]
        strategy = "tags"            # "tags" = what Redgifs' own client sends; "search_text" = old way, last resort
        filter_on = False

        results, images_kept, videos_kept, sampled = [], 0, 0, False
        page = 1
        scanned = 0
        while len(results) < limit and not stop_event.is_set():
            if mode == "niche":
                url = f"{API}/v2/niches/{urllib.parse.quote(tag, safe='')}/gifs?" + urllib.parse.urlencode(
                    {"order": NICHE_ORDER.get(order, "best"), "count": PAGE_SIZE, "page": page})
            else:
                params = {"type": "g", "order": order, "count": PAGE_SIZE, "page": page}
                if mode == "text":
                    params["query"] = tag
                elif strategy == "tags":
                    params["tags"] = ",".join(terms)
                else:
                    params["search_text"] = tag
                url = f"{API}/v2/gifs/search?" + urllib.parse.urlencode(params)
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
            raw_count = len(gifs)
            if mode == "text":                           # the site's text search is loose: keep real mentions only
                gifs = [g for g in gifs if _words_in(g, tag)]
                if not gifs and raw_count == PAGE_SIZE and page < 5:
                    page += 1
                    continue
            if not gifs:
                if page == 1 and strategy == "tags" and len(terms) > 1:
                    log(f"No results for all of {terms} together - trying just '{terms[0]}'", "warning")
                    terms = terms[:1]
                    continue
                if page == 1:
                    log(f"No Redgifs results for '{tag}' (searched {strategy}={','.join(terms) if strategy == 'tags' else tag!r}).",
                        "warning")
                break
            hit, listed = self._tag_hits(gifs, terms) if mode == "tags" else (0, 0)
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
                if (skip_ids and f"rg_{gif_id}" in skip_ids) or gif_id in self.seen_ids:
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
                wanted = getattr(self, "wanted_types", None)
                if wanted and media_type not in wanted:
                    continue                             # not a type you ticked: don't download it
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
                self.seen_ids.add(gif_id)

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

            if raw_count < PAGE_SIZE:
                break  # last page
            page += 1

        progress(len(results), max(len(results), 1), "Done")
        log(f"--- Redgifs '{tag}': {len(results)} item(s) collected ---")
        return results

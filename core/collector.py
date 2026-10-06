"""Headless collection engine: a Collection (folder + memory of what was fetched/rejected) and a Job that runs
a list of Picks (site + search value) in one worker thread and reports through an event queue.
No UI imports, so it is fully testable."""
import json
import os
import queue
import threading
import time
import traceback
import zipfile
from dataclasses import dataclass, field

from core import netlog
from core.thumbs import looks_like_error_page, make_thumb
from core.util import safe_name
from sources import SOURCE_BY_ID

MANIFEST = "collection.json"


@dataclass
class Pick:
    source_id: str
    value: str          # exactly what is typed into that site's search (tag, subreddit, creator, ...)
    label: str = ""     # display text
    quality: str = ""   # Any / Good / Best; "" = the job's default
    limit: int = 0      # items to fetch; 0 = the job's default

    def key(self):
        return (self.source_id, self.value.strip().lower())

    def to_dict(self):
        return {"source": self.source_id, "value": self.value, "label": self.label,
                "quality": self.quality, "limit": self.limit}

    @classmethod
    def from_dict(cls, d):
        try:
            return cls(str(d["source"]), str(d["value"]), str(d.get("label", "")),
                       str(d.get("quality", "")), int(d.get("limit", 0) or 0))
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class Options:
    limit: int = 50
    quality: str = "Good"                       # Any / Good / Best
    types: set = field(default_factory=lambda: {"image", "video"})
    randomize: bool = False
    sort: str = ""                              # Advanced: site's own sort (blank = from quality)
    time_range: str = ""


class Collection:
    """A themed folder. collection.json remembers every post id ever fetched so repeat runs add new items."""

    def __init__(self, root, name):
        self.name = name
        self.dir = os.path.join(root, safe_name(name, "collection"))
        self.seen = set()
        self.rejected = set()
        self.picks = []          # saved searches (list of Pick), so a collection reopens as you left it
        self._lock = threading.Lock()
        self._load()

    def _path(self):
        return os.path.join(self.dir, MANIFEST)

    def _load(self):
        try:
            with open(self._path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            self.seen = set(data.get("seen", []))
            self.rejected = set(data.get("rejected", []))
            self.picks = [p for p in (Pick.from_dict(d) for d in data.get("picks", [])) if p]
        except (OSError, ValueError, AttributeError, TypeError):
            pass

    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        with self._lock:
            payload = {"seen": sorted(self.seen), "rejected": sorted(self.rejected),
                       "picks": [p.to_dict() for p in self.picks]}
        tmp = self._path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, self._path())

    def mark_seen(self, post_id):
        with self._lock:
            self.seen.add(post_id)

    def reject(self, post_id, file_path):
        """Delete the file and never fetch that post again."""
        with self._lock:
            self.seen.add(post_id)
            self.rejected.add(post_id)
        try:
            os.remove(file_path)
        except OSError:
            pass

    def skip_ids(self):
        with self._lock:
            return set(self.seen)

    def export_zip(self, dest_zip):
        """Zip the collection's media (not its bookkeeping file). Returns the file count."""
        n = 0
        with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_STORED) as z:
            for base, _, files in os.walk(self.dir):
                for fn in files:
                    if fn == MANIFEST or fn.endswith(".tmp"):
                        continue
                    full = os.path.join(base, fn)
                    z.write(full, os.path.relpath(full, self.dir))
                    n += 1
        return n


class CombinedStop:
    """is_set() when either event is set (the job's stop button, or a per-pick cancel)."""
    def __init__(self, *events):
        self.events = events

    def is_set(self):
        return any(e.is_set() for e in self.events)

    def wait(self, timeout=None):
        return self.is_set()


class Job:
    """Runs picks one after another (keeps each site's rate limit) off the UI thread.
    Events on self.events: ("log", msg, level) ("progress", cur, total, prefix) ("item", pick, item, thumb)
    ("pick_done", pick, count, status, detail) ("done", total, stopped)."""

    def __init__(self, collection, picks, options, credentials=None):
        self.collection, self.picks, self.options = collection, list(picks), options
        self.credentials = credentials or {}
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None
        self.total = 0

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _emit(self, *event):
        self.events.put(event)

    def _run(self):
        try:
            for pick in self.picks:
                if self.stop_event.is_set():
                    break
                self._run_pick(pick)
        finally:
            try:
                self.collection.save()
            except OSError as ex:
                self._emit("log", f"Couldn't save collection memory: {ex}", "error")
            self._emit("done", self.total, self.stop_event.is_set())

    def _run_pick(self, pick):
        cls = SOURCE_BY_ID.get(pick.source_id)
        label = f"{cls.label if cls else pick.source_id}: {pick.value}"
        if cls is None:
            self._emit("pick_done", pick, 0, "failed", "unknown site")
            return
        opts = self.options
        quality = pick.quality or opts.quality
        limit = pick.limit or opts.limit
        resolved = cls.resolve_quality(quality) if cls.supports_quality else {}
        sort = (opts.sort or resolved.get("sort") or None) if cls.has_sort else None
        time_range = (opts.time_range or resolved.get("time_range") or None) if cls.has_sort else None
        query = pick.value
        suffix = resolved.get("query_suffix")
        if suffix and "score" not in query:
            query = f"{query} {suffix}"
        dest = os.path.join(self.collection.dir, safe_name(cls.label), safe_name(pick.value)[:40])
        os.makedirs(dest, exist_ok=True)
        creds = self.credentials.get(pick.source_id) or {}
        self._emit("log", f"[{label}] START quality={quality} limit={limit} -> query={query!r} sort={sort} "
                          f"time={time_range} shuffle={opts.randomize} types={sorted(opts.types)} "
                          f"credentials_set={sorted(creds)} dest={dest}", "debug")
        try:
            source = cls(**creds) if creds else cls()
        except TypeError as ex:
            self._emit("pick_done", pick, 0, "failed", f"bad settings for this site: {ex}")
            return

        errors, kept, skipped = [], [], {"error_page": 0, "type": 0}

        def log_cb(msg, level="info"):
            if level == "error":
                errors.append(msg)
            self._emit("log", f"[{label}] {msg}", level)

        def progress_cb(cur, total, prefix):
            self._emit("progress", cur, total, f"{prefix}: {label}")

        def item_cb(item):
            if looks_like_error_page(item.file_path):
                skipped["error_page"] += 1
                log_cb(f"discarded {os.path.basename(item.file_path)}: an error page, not a real file", "warning")
                _rm(item.file_path)
                return
            if item.media_type not in opts.types:
                skipped["type"] += 1
                self._emit("log", f"[{label}] dropped {item.post_id} ({item.media_type} not selected)", "debug")
                _rm(item.file_path)
                self.collection.mark_seen(item.post_id)     # don't re-download a type you excluded
                return
            self.collection.mark_seen(item.post_id)
            kept.append(item)
            self.total += 1
            self._emit("log", f"[{label}] kept {item.post_id} {item.media_type} "
                              f"{os.path.getsize(item.file_path)} bytes -> {item.file_path}", "debug")
            self._emit("item", pick, item, make_thumb(item.file_path, item.media_type))

        http = []
        netlog.begin(http)
        status, detail = "done", ""
        started = time.time()
        try:
            source.fetch(query, limit, sort, time_range, dest, log_cb, progress_cb,
                         CombinedStop(self.stop_event), None, opts.randomize, False,
                         item_cb=item_cb, skip_ids=self.collection.skip_ids())
        except Exception as ex:                     # a broken site must not stop the other picks
            status, detail = "failed", f"{type(ex).__name__}: {ex}"
            self._emit("log", f"[{label}] CRITICAL: {detail}\n{traceback.format_exc()}", "error")
        finally:
            netlog.end()
        for h in http:
            line = f"HTTP {h.get('status')} {h.get('ms')}ms {h.get('url')}"
            if h.get("retry"):
                line += f" (retry {h['retry']})"
            if h.get("error"):
                line += f" ERROR {h['error']}"
            if h.get("body") and (h.get("status") not in (200, 206) or h.get("error")):
                line += f" body={h['body'][:200]!r}"
            self._emit("log", f"[{label}] {line}", "debug")
        if status == "done":
            if self.stop_event.is_set() and len(kept) < limit:
                status = "stopped"
            elif not kept and errors:
                status, detail = "failed", errors[-1]
            elif not kept:
                status, detail = "empty", "nothing new matched"
        self._emit("log", f"[{label}] END status={status} kept={len(kept)} skipped={skipped} "
                          f"http_calls={len(http)} seconds={time.time() - started:.1f}", "debug")
        self.collection.save()
        self._emit("pick_done", pick, len(kept), status, detail)


def _rm(path):
    try:
        os.remove(path)
    except OSError:
        pass


def suggest_all(query, source_ids=None, timeout=10.0, min_count=0, max_results=80):
    """Ask every site that supports it for real matches. Returns the most popular first across ALL sites:
    [{"source": id, "site": label, "value", "label", "count"}]. Matches with a known size under min_count are
    dropped; matches with no known size go last. A slow or broken site just contributes nothing."""
    ids = source_ids or list(SOURCE_BY_ID)
    results, lock = [], threading.Lock()

    def one(sid):
        cls = SOURCE_BY_ID[sid]
        try:
            found = cls.suggest(query) or []
        except Exception:
            found = []
        with lock:
            for m in found:
                results.append({"source": sid, "site": cls.label, "value": m["value"],
                                "label": m.get("label") or m["value"], "count": m.get("count")})

    threads = [threading.Thread(target=one, args=(sid,), daemon=True) for sid in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout)
    seen, out = set(), []
    for r in results:
        key = (r["source"], str(r["value"]).lower())
        if key in seen:
            continue
        seen.add(key)
        if r["count"] is not None and r["count"] < min_count:
            continue
        out.append(r)
    out.sort(key=lambda r: (r["count"] is None, -(r["count"] or 0)))
    return out[:max_results]

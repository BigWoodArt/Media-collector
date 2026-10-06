"""Headless collection engine: a Collection (folder + memory of what was fetched/rejected) and a Job that runs
a list of Picks (site + search value) in one worker thread and reports through an event queue.
No UI imports, so it is fully testable."""
import json
import os
import queue
import tempfile
import threading
import time
import traceback
import zipfile
from dataclasses import dataclass, field

from core import netlog
from core.thumbs import looks_like_error_page, make_thumb
from core.util import safe_name

from concurrent.futures import ThreadPoolExecutor

from sources import SOURCE_BY_ID, SOURCE_CLASSES
from sources.base import Source

MANIFEST = "collection.json"


def add_tokens(query, suffix):
    """Append each suffix token (sort:score, score:>=10) unless the query already has one of that kind."""
    have = query.split()
    for token in (suffix or "").split():
        kind = token.split(":", 1)[0] + ":"
        if not any(t.lstrip("-").startswith(kind) for t in have):
            query += " " + token
    return query


@dataclass
class Pick:
    source_id: str
    value: str          # exactly what is typed into that site's search (tag, subreddit, creator, ...)
    label: str = ""     # display text
    order: str = ""     # the site's own sort choice key ("" = site default)
    min_score: str = ""  # boorus: minimum-score choice key ("" = none)
    limit: int = 0      # items to fetch; 0 = the job's default
    types: str = ""     # comma list of image,video,audio; "" = the job's default
    randomize: bool = False
    prioritize: bool = False
    status: str = ""    # last result: done / empty / failed / stopped ("" = never run)
    kept: int = 0       # items kept in the last run

    def key(self):
        return (self.source_id, self.value.strip().lower())

    def type_set(self):
        return {t for t in self.types.split(",") if t}

    def to_dict(self):
        return {"source": self.source_id, "value": self.value, "label": self.label, "order": self.order,
                "min_score": self.min_score, "limit": self.limit, "types": self.types,
                "randomize": self.randomize, "prioritize": self.prioritize,
                "status": self.status, "kept": self.kept}

    @classmethod
    def from_dict(cls, d):
        try:
            return cls(str(d["source"]), str(d["value"]), str(d.get("label", "")), str(d.get("order", "")),
                       str(d.get("min_score", "")), int(d.get("limit", 0) or 0), str(d.get("types", "")),
                       bool(d.get("randomize")), bool(d.get("prioritize")), str(d.get("status", "")),
                       int(d.get("kept", 0) or 0))
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class Options:
    limit: int = 50
    types: set = field(default_factory=lambda: {"image", "video"})   # used when a pick has no types of its own


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
        limit = pick.limit or opts.limit or cls.default_limit
        types = pick.type_set() or opts.types
        resolved = cls.resolve(pick.order, pick.min_score)
        sort, time_range = resolved.get("sort"), resolved.get("time_range")
        query = add_tokens(pick.value, resolved.get("query_suffix", ""))
        dest = os.path.join(self.collection.dir, safe_name(cls.label), safe_name(pick.value)[:40])
        os.makedirs(dest, exist_ok=True)
        creds = self.credentials.get(pick.source_id) or {}
        self._emit("log", f"[{label}] START order={pick.order or cls.default_order!r} min_score={pick.min_score!r} limit={limit} -> "
                          f"query={query!r} sort={sort} time={time_range} shuffle={pick.randomize} "
                          f"prioritize={pick.prioritize} types={sorted(types)} "
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
            if item.media_type not in types:
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
                         CombinedStop(self.stop_event), None, pick.randomize, pick.prioritize,
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
        pick.status, pick.kept = status, len(kept)
        self.collection.save()
        self._emit("pick_done", pick, len(kept), status, detail)


def _rm(path):
    try:
        os.remove(path)
    except OSError:
        pass


def suggest_all(query, source_ids=None, timeout=12.0, min_count=0, max_results=80, report=None):
    """Ask every site that supports it for real matches. Returns the most popular first across ALL sites:
    [{"source": id, "site": label, "value", "label", "count"}]. Matches with a known size under min_count are
    dropped; matches with no known size go last. A slow or broken site just contributes nothing."""
    ids = source_ids or list(SOURCE_BY_ID)
    results, lock = [], threading.Lock()

    def one(sid):
        cls = SOURCE_BY_ID[sid]
        t0 = time.time()
        try:
            found = cls.suggest(query) or []
        except Exception:
            found = []
        if report and cls.suggest.__func__ is not Source.suggest.__func__:    # only sites that have a lookup
            report(cls.label, len(found), round(time.time() - t0, 1))
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
    names = {query.strip().lower().lstrip("#"), query.strip().lower().replace(" ", ""),
             query.strip().lower().replace(" ", "_")}
    out.sort(key=lambda r: (str(r["value"]).lower() not in names, r["count"] is None, -(r["count"] or 0)))
    return out[:max_results]


def check_sites(credentials=None, on_result=None, stop_event=None, workers=6):
    """One tiny harmless search (limit 1) per site: which sources answer right now?
    Returns (results, temp_dir). Each result: {"id","label","result": ok|empty|fail|stopped, "elapsed",
    "detail","http","item","thumb"}. on_result(result) is called from worker threads as each site finishes."""
    credentials = credentials or {}
    stop_event = stop_event or threading.Event()
    root = tempfile.mkdtemp(prefix="mc_sitecheck_")
    results = []

    def one(cls):
        res = {"id": cls.id, "label": cls.label, "query": cls.check_query, "result": "fail", "elapsed": 0.0,
               "detail": "", "http": [], "item": None, "thumb": None}
        if stop_event.is_set():
            res["result"] = "stopped"
            return res
        dest = os.path.join(root, safe_name(cls.id))
        os.makedirs(dest, exist_ok=True)
        creds = credentials.get(cls.id) or {}
        errors, items, http = [], [], []
        started = time.time()
        netlog.begin(http)
        try:
            source = cls(**creds) if creds else cls()
            resolved = cls.resolve("", "")
            source.fetch(add_tokens(cls.check_query, resolved.get("query_suffix", "")), 1,
                         resolved.get("sort"), resolved.get("time_range"), dest,
                         lambda m, lvl="info": errors.append(m) if lvl == "error" else None,
                         lambda *a: None, CombinedStop(stop_event), None, False, False,
                         item_cb=items.append, skip_ids=set())
        except Exception as ex:
            res["detail"] = f"{type(ex).__name__}: {ex}"
        finally:
            netlog.end()
        res["elapsed"], res["http"] = round(time.time() - started, 1), http
        good = [i for i in items if not looks_like_error_page(i.file_path)]
        if good:
            res["result"], res["item"] = "ok", good[0]
            res["thumb"] = make_thumb(good[0].file_path, good[0].media_type)
        elif stop_event.is_set():
            res["result"] = "stopped"
        elif res["detail"] or errors:
            res["detail"] = res["detail"] or errors[-1]
        else:
            res["result"], res["detail"] = "empty", "answered, but nothing matched"
        return res

    def wrapped(cls):
        r = one(cls)
        results.append(r)
        if on_result:
            try:
                on_result(r)
            except Exception:
                pass
        return r

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(wrapped, SOURCE_CLASSES))
    results.sort(key=lambda r: r["label"].lower())
    return results, root

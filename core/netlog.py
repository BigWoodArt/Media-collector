"""Wraps urllib.request.urlopen: logs each call per thread, redacts secrets, retries transient errors twice."""
import io
import re
import socket
import threading
import time
import urllib.error
import urllib.request

_local = threading.local()


class DownloadInterrupted(Exception):
    """Raised inside a download when the user pressed Stop or Skip (or the file exceeds the size limit)."""


class DownloadControl:
    """Per-thread hooks for downloads: stop (Event-like), skip (Event), a size cap and a progress callback.
    on_progress(done_bytes, total_bytes_or_0, bytes_per_second, url); a final call has done == total == 0."""
    def __init__(self, stop, skip, max_bytes=0, on_progress=None):
        self.stop, self.skip, self.max_bytes, self.on_progress = stop, skip, max_bytes, on_progress


def set_control(ctl):
    _local.ctl = ctl


def clear_control():
    _local.ctl = None


def set_site_check(enabled=True, stop_event=None):
    """Mark the current worker as a site-check probe. Site checks must never
    inherit long media-download timeouts or transient retries."""
    _local.site_check = bool(enabled)
    _local.site_check_stop = stop_event if enabled else None


def clear_site_check():
    _local.site_check = False
    _local.site_check_stop = None


def is_site_check():
    return bool(getattr(_local, "site_check", False))


_TEXTY = ("json", "text", "xml", "html", "javascript")
PROGRESS_MIN = 262144        # don't report tiny API replies


class _Stream:
    """Wraps a response for a job thread: reads in small steps so Stop/Skip act within about a second,
    enforces the size cap and reports progress. Everything else is passed through."""

    def __init__(self, resp, ctl, url):
        self._r, self._ctl, self._url = resp, ctl, url
        self._done, self._t0, self._last = 0, time.time(), 0.0
        try:
            self._total = int(resp.headers.get("Content-Length") or 0)
        except Exception:
            self._total = 0
        try:
            self._texty = any(t in (resp.headers.get("Content-Type") or "").lower() for t in _TEXTY)
        except Exception:
            self._texty = True
        try:                             # short socket waits so a stalled transfer can be interrupted
            resp.fp.raw._sock.settimeout(1.0)
            self._short = True
        except Exception:
            self._short = False
        self._idle_limit = 8.0 if is_site_check() else 30.0

    def __getattr__(self, name):
        return getattr(self._r, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        self._r.close()

    def _check(self):
        if self._ctl.stop.is_set():
            raise DownloadInterrupted("Stopped by user")
        if self._ctl.skip.is_set() and not self._texty:     # API pages are never skipped, only files
            self._ctl.skip.clear()
            raise DownloadInterrupted("Skipped by user")
        cap = self._ctl.max_bytes
        if cap and not self._texty and (self._total > cap or self._done > cap):
            raise DownloadInterrupted(f"Skipped: larger than the {cap // 1048576} MB limit")

    def _report(self, final=False):
        cb = self._ctl.on_progress
        if not cb or self._texty:
            return
        now = time.time()
        if final:
            if self._reported:
                cb(0, 0, 0.0, self._url)
            return
        if self._done < PROGRESS_MIN and self._total < PROGRESS_MIN:
            return
        if now - self._last >= 0.25:
            self._last, self._reported = now, True
            cb(self._done, self._total, self._done / max(now - self._t0, 0.001), self._url)

    _reported = False

    def _step(self, n):
        idle = time.time()
        while True:
            self._check()
            try:
                if self._short and hasattr(self._r, "read1"):
                    data = self._r.read1(n)
                else:
                    data = self._r.read(n)
                return data
            except (socket.timeout, TimeoutError):
                if time.time() - idle > self._idle_limit:
                    raise

    def read(self, amt=None):
        if amt is not None and amt >= 0:
            data = self._step(amt)
            self._done += len(data)
            self._report(final=not data)
            return data
        chunks = []
        try:
            while True:
                data = self._step(65536)
                if not data:
                    break
                chunks.append(data)
                self._done += len(data)
                self._report()
        finally:
            self._report(final=True)
        return b"".join(chunks)
_orig_urlopen = urllib.request.urlopen
_installed = False
_SECRET_RE = re.compile(r"((?:token|api_key|apikey|user_id|key)=)[^&\s]+", re.I)
MAX_CALLS = 300


def redact(url: str) -> str:
    return _SECRET_RE.sub(r"\1***", url)


def _record(url, status, started, error=None, body=b"", retry=None):
    calls = getattr(_local, "calls", None)
    if calls is None:
        return
    if len(calls) >= MAX_CALLS:
        return
    entry = {"url": redact(url), "status": status,
             "ms": int((time.time() - started) * 1000)}
    if retry:
        entry["retry"] = retry
    if error:
        entry["error"] = str(error)[:200]
    if body:
        entry["body"] = re.sub(r"\s+", " ", body[:300].decode("utf-8", "replace")).strip()
    calls.append(entry)


RETRY_DELAYS = (1.5, 4.0)          # seconds before retry 1 and 2
TRANSIENT_HTTP = {500, 502, 503, 504}


def _is_transient(exc):
    """Retry timeouts, resets and HTTP 5xx; not 4xx, 429 or DNS failures."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in TRANSIENT_HTTP
    if isinstance(exc, urllib.error.URLError):
        return not isinstance(exc.reason, socket.gaierror)
    return isinstance(exc, (socket.timeout, TimeoutError, ConnectionError))


def _wrapped(req, *args, **kwargs):
    url = getattr(req, "full_url", None) or str(req)
    attempt = 0
    site_check = is_site_check()
    if site_check:
        # A site check is a health probe, not a download. Never let a dead
        # media host consume the normal 20-45 second media timeout.
        if args:
            args = list(args)
            if len(args) >= 2 and isinstance(args[1], (int, float)):
                args[1] = min(args[1], 8.0)
            args = tuple(args)
        if "timeout" in kwargs and isinstance(kwargs["timeout"], (int, float)):
            kwargs["timeout"] = min(kwargs["timeout"], 8.0)
    while True:
        started = time.time()
        try:
            resp = _orig_urlopen(req, *args, **kwargs)
        except Exception as e:
            body = b""
            if isinstance(e, urllib.error.HTTPError):
                try:                   # keep the reply text: 401/403 pages usually say why
                    body = e.read()
                    bio = io.BytesIO(body)
                    e.read, e.fp = bio.read, bio   # let later readers still get the body
                except Exception:
                    pass
            retry = (not site_check) and _is_transient(e) and attempt < len(RETRY_DELAYS)
            _record(url, getattr(e, "code", None), started, e, body, attempt if attempt else None)
            if not retry:
                raise
            time.sleep(RETRY_DELAYS[attempt])
            attempt += 1
            continue
        status = getattr(resp, "status", None)
        if status is None and hasattr(resp, "getcode"):
            status = resp.getcode()
        _record(url, status, started, retry=attempt if attempt else None)
        ctl = getattr(_local, "ctl", None)
        if ctl is None and site_check:
            ctl = DownloadControl(
                getattr(_local, "site_check_stop", None) or threading.Event(),
                threading.Event(), 0, None
            )
        return _Stream(resp, ctl, url) if ctl else resp


def install():
    global _installed
    if not _installed:
        urllib.request.urlopen = _wrapped
        _installed = True


def begin(calls_list: list):
    _local.calls = calls_list


def end():
    _local.calls = None

"""Wraps urllib.request.urlopen: logs each call per thread, redacts secrets, retries transient errors twice."""
import io
import re
import socket
import threading
import time
import urllib.error
import urllib.request

_local = threading.local()
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
            retry = _is_transient(e) and attempt < len(RETRY_DELAYS)
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
        return resp


def install():
    global _installed
    if not _installed:
        urllib.request.urlopen = _wrapped
        _installed = True


def begin(calls_list: list):
    _local.calls = calls_list


def end():
    _local.calls = None

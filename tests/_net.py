"""Test helper: fake the network at the single urlopen chokepoint (core/netlog.py)."""
import io
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core import netlog          # noqa: E402
from sources import SOURCE_BY_ID  # noqa: E402

netlog.install()


def reply(body, status=200):
    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    r = Resp(body if isinstance(body, bytes) else str(body).encode())
    r.status, r.getcode = status, (lambda: status)
    return r


def err(url, code, body=b""):
    import urllib.error
    return urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(body))


def fetch(site, query, handler, limit=10, creds=None, skip=None, **kw):
    """Run a real source against handler(url) -> reply | raises. Returns (items, urls, log, http)."""
    urls, log, http, got = [], [], [], []

    def fake(req, timeout=15):
        urls.append(req.full_url)
        return handler(req.full_url)
    with mock.patch("time.sleep"), mock.patch.object(netlog, "_orig_urlopen", fake):
        urllib.request.urlopen = netlog._wrapped
        cls = SOURCE_BY_ID[site]
        src = cls(**creds) if creds else cls()
        netlog.begin(http)
        try:
            items = src.fetch(query, limit, kw.get("sort"), kw.get("time_range"), tempfile.mkdtemp(),
                              lambda m, l="info": log.append((l, m)), lambda *a: None,
                              threading.Event(), None, kw.get("randomize", False),
                              kw.get("prioritize_images", False), item_cb=got.append, skip_ids=skip)
        finally:
            netlog.end()
    return items, urls, log, http, got

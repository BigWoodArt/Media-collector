import json
import tempfile
import threading
import unittest
from unittest import mock

from core import collector, netlog
from sources.coomer_source import CoomerSource
from sources.kemono_source import KemonoSource
from sources.erome_source import EromeSource


class SiteCheckFixes(unittest.TestCase):
    def test_coomer_bare_username_suggestion_does_not_need_creators_api(self):
        r = CoomerSource.suggest("soleilretro")
        self.assertEqual(r[0]["value"], "onlyfans/user/soleilretro")
        self.assertTrue(r[0]["nofilter"])

    def test_site_check_flag_disables_retries(self):
        calls = []
        with mock.patch.object(netlog, "_orig_urlopen", side_effect=OSError("unreachable")) as op:
            netlog.begin(calls)
            netlog.set_site_check(True)
            try:
                with self.assertRaises(OSError):
                    netlog._wrapped("https://example.invalid/file.mp4", timeout=45)
            finally:
                netlog.clear_site_check()
                netlog.end()
        self.assertEqual(op.call_count, 1)

    def test_json_board_site_check_uses_probe_item(self):
        from sources.e621_source import E621Source
        s = E621Source()
        s._site_check = True
        s._page = lambda q, c: ([{"id": "1", "url": "https://x/1.jpg", "tags": [], "title": "x"}], None)
        with mock.patch("urllib.request.urlopen", side_effect=lambda req, timeout=8: type("R", (), {
            "status": 206, "getcode": lambda self: 206, "read": lambda self, n=-1: b"x", "__enter__": lambda self: self, "__exit__": lambda *a: None
        })()):
            with tempfile.TemporaryDirectory() as d:
                items = s.fetch("cats", 1, "", "", d, lambda *a: None, lambda *a: None,
                                threading.Event(), item_cb=None, skip_ids=set())
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].extra["site_check"])
        self.assertEqual(items[0].file_path, "")


if __name__ == "__main__":
    unittest.main()


class MirrorOverride(unittest.TestCase):
    def test_base_url_overrides_root(self):
        self.assertEqual(CoomerSource(base_url="coomer.su/").root, "https://coomer.su")
        self.assertEqual(KemonoSource().root, "https://kemono.cr")
        self.assertEqual(KemonoSource(base_url="https://kemono.su")._media_url("/ab/cd/x.jpg"),
                         "https://kemono.su/data/ab/cd/x.jpg")


class PreviewFallback(unittest.TestCase):
    def _run(self, full_ok):
        import os
        s = CoomerSource()
        posts = [{"id": "1", "title": "t", "file": {"path": "/ab/cd/x.jpg", "name": "x.jpg"}}]
        calls = []

        def req(url, timeout=20, referer=None):
            calls.append(url)
            if "/thumbnail/" in url:
                return b"thumbbytes"
            if full_ok:
                return b"fullbytes"
            raise OSError("unreachable")
        s._request, s._json = req, lambda url: posts
        s._wait = lambda: None
        with tempfile.TemporaryDirectory() as d:
            items = s.fetch("onlyfans/user/a", 1, "", "", d, lambda *a: None, lambda *a: None, threading.Event())
            names = [os.path.basename(i.file_path) for i in items]
        return items, names, calls

    def test_falls_back_to_preview(self):
        items, names, calls = self._run(False)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].extra["preview"])
        self.assertIn("_preview", names[0])
        self.assertIn("https://img.coomer.st/thumbnail/data/ab/cd/x.jpg", calls)

    def test_full_size_preferred(self):
        items, names, calls = self._run(True)
        self.assertFalse(items[0].extra["preview"])
        self.assertFalse(any("/thumbnail/" in c for c in calls))


class BareCoomerName(unittest.TestCase):
    def test_suggest_finds_the_service_that_has_it(self):
        def state(root, svc, cid):
            return ("yes", "Queen Of Milk") if svc == "fansly" else ("no", "")
        with mock.patch.object(CoomerSource, "_profile_state", side_effect=state):
            r = CoomerSource.suggest("Queenofmilk")
        self.assertEqual([x["value"] for x in r], ["fansly/user/queenofmilk"])

    def test_suggest_offline_still_guesses_onlyfans(self):
        with mock.patch.object(CoomerSource, "_profile_state", return_value=("unknown", "")):
            self.assertEqual(CoomerSource.suggest("someone")[0]["value"], "onlyfans/user/someone")

    def test_fetch_uses_found_service(self):
        s = CoomerSource()
        urls = []
        s._json = lambda u: urls.append(u) or []
        with mock.patch.object(CoomerSource, "_profile_state", side_effect=lambda r, sv, c: ("yes", "x") if sv == "candfans" else ("no", "")):
            with tempfile.TemporaryDirectory() as d:
                s.fetch("Queenofmilk", 1, "", "", d, lambda *a: None, lambda *a: None, threading.Event())
        self.assertIn("/api/v1/candfans/user/queenofmilk/posts", urls[0])


class CoomerNamesAndStop(unittest.TestCase):
    def test_display_name_matches_ignoring_spaces(self):
        from sources import kemono_source as ks
        ks.CREATOR_CACHE["coomer"] = (__import__("time").time(),
                                      [{"name": "Queen Of Milk", "service": "fansly", "id": "549327668156313600", "favorited": 5}])
        r = CoomerSource._creator_matches("Queenofmilk")
        ks.CREATOR_CACHE.clear()
        self.assertEqual(r[0]["value"], "fansly/user/549327668156313600")

    def test_stop_interrupts_a_hung_api_call(self):
        import time
        s = CoomerSource()
        s._json = lambda u: time.sleep(30)
        stop = threading.Event()
        threading.Timer(0.5, stop.set).start()
        t0 = time.time()
        with tempfile.TemporaryDirectory() as d:
            s.fetch("fansly/user/1", 1, "", "", d, lambda *a: None, lambda *a: None, stop)
        self.assertLess(time.time() - t0, 3)


class FastFallbackAndStop(unittest.TestCase):
    def test_blocked_full_size_costs_one_try_then_previews(self):
        s = CoomerSource()
        calls = []

        def req(url, timeout=20, referer=None):
            calls.append((url, timeout))
            if "/thumbnail/" in url:
                return b"x"
            raise OSError("unreachable")
        s._request = req
        data, used = s._get_media("https://coomer.st/data/ab/cd/x.jpg", "https://coomer.st/p")
        self.assertTrue(s.last_was_preview)
        self.assertEqual(len([c for c in calls if "/thumbnail/" not in c[0]]), 1)     # no n1..n4 walk
        self.assertLessEqual(calls[0][1], 15)
        s._get_media("https://coomer.st/data/ab/cd/y.jpg", "https://coomer.st/p")
        self.assertEqual(len([c for c in calls if "/thumbnail/" not in c[0]]), 1)     # blocked flag remembered

    def test_stop_interrupts_a_hung_download(self):
        import time
        s = CoomerSource()
        s._json = lambda u: [{"id": "1", "title": "t", "file": {"path": "/ab/cd/x.jpg", "name": "x.jpg"}}]
        s._get_media = lambda *a, **k: time.sleep(30)
        stop = threading.Event()
        threading.Timer(0.5, stop.set).start()
        t0 = time.time()
        with tempfile.TemporaryDirectory() as d:
            s.fetch("fansly/user/1", 1, "", "", d, lambda *a: None, lambda *a: None, stop)
        self.assertLess(time.time() - t0, 3)


class SiteCheckSampleImage(unittest.TestCase):
    def test_image_result_is_really_downloaded(self):
        import http.server, os, socketserver
        png = (b"\x89PNG\r\n\x1a\n" + b"0" * 200)

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(png)

            def log_message(self, *a):
                pass
        srv = socketserver.TCPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            from core.media_item import MediaItem
            item = MediaItem(file_path="", caption="c", media_type="image", source_label="x", post_id="1",
                             source_type="e621", extra={"site_check": True,
                                                        "probe_url": f"http://127.0.0.1:{srv.server_address[1]}/a.png"})
            from sources.e621_source import E621Source
            with tempfile.TemporaryDirectory() as d:
                path = collector._fetch_sample_image(E621Source(), item, d, threading.Event())
                self.assertTrue(os.path.exists(path))
                self.assertEqual(open(path, "rb").read(), png)
        finally:
            srv.shutdown()

    def test_html_instead_of_image_is_rejected(self):
        self.assertTrue(collector.looks_like_error_page_bytes(b"<!doctype html><html>"))
        self.assertFalse(collector.looks_like_error_page_bytes(b"\x89PNG\r\n"))


class TypesAndVideos(unittest.TestCase):
    def test_video_fails_fast_when_server_blocked(self):
        s = CoomerSource()
        calls = []

        def req(url, timeout=20, referer=None):
            calls.append(url)
            raise OSError("unreachable")
        s._request = req
        for _ in range(2):
            with self.assertRaises(OSError):
                s._get_media("https://coomer.st/data/ab/cd/v.mp4", "https://coomer.st/p")
        self.assertEqual(len(calls), 1)         # one try total; no n1..n4 walk, no repeat

    def test_unwanted_type_is_not_downloaded(self):
        s = CoomerSource()
        s.wanted_types = {"image"}
        s._json = lambda u: [{"id": "1", "title": "t", "file": {"path": "/ab/cd/v.mp4", "name": "v.mp4"}}]
        got = []
        s._get_media = lambda *a, **k: got.append(a) or (b"x", a[0])
        with tempfile.TemporaryDirectory() as d:
            s.fetch("fansly/user/1", 1, "", "", d, lambda *a: None, lambda *a: None, threading.Event())
        self.assertEqual(got, [])


class WantedTypesEverywhere(unittest.TestCase):
    def test_audio_sources_skip_when_audio_not_selected(self):
        from sources.soundgasm_source import SoundgasmSource
        from sources.freesound_source import FreesoundSource
        logs = []
        for s in (SoundgasmSource(), FreesoundSource(api_key="k")):
            s.wanted_types = {"image", "video"}
            self.assertEqual(s.fetch("x", 1, "", "", tempfile.gettempdir(), lambda m, l="info": logs.append(m),
                                     lambda *a: None, threading.Event()), [])
        self.assertEqual(sum("audio isn't one of the selected types" in m for m in logs), 2)

    def test_every_downloading_source_checks_wanted_types(self):
        import glob, os
        missing = []
        for p in glob.glob(os.path.join(os.path.dirname(collector.__file__), "..", "sources", "*_source.py")):
            src = open(p, encoding="utf-8").read()
            if "def fetch" in src and "wanted_types" not in src and "JsonBoardSource" not in src:
                missing.append(os.path.basename(p))
        self.assertEqual(missing, [])

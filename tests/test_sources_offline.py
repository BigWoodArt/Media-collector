"""Offline tests for every scraper: python -m unittest discover tests"""
import inspect
import io
import json
import os
import socket
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

from tests._net import fetch, reply, netlog
from sources import SOURCE_CLASSES, SOURCE_BY_ID, SOURCES_VERSION
from core.thumbs import looks_like_error_page

MD5 = lambda n: f"{n:032x}"
HASH40 = lambda n: f"{n:040x}"


def err(url, code, body=b""):
    return urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(body))


class Contract(unittest.TestCase):
    def test_every_source_has_the_expected_shape(self):
        ids = set()
        for c in SOURCE_CLASSES:
            with self.subTest(site=c.id):
                for attr in ("id", "label", "category", "check_query", "default_limit", "default_randomize",
                             "priority_media", "default_prioritize"):
                    self.assertTrue(hasattr(c, attr), attr)
                params = inspect.signature(c.fetch).parameters
                for p in ("item_cb", "skip_ids", "randomize", "prioritize_images", "early_preview_cb"):
                    self.assertIn(p, params)
                self.assertIn(c.priority_media, ("image", "video"))
                self.assertNotIn(c.id, ids)
                ids.add(c.id)
                self.assertIsInstance(c.resolve_quality("Good"), dict)
        self.assertRegex(SOURCES_VERSION, r"^\d{4}\.\d{2}\.\d{2}")

    def test_booru_post_id_prefixes_are_unique(self):
        from sources.booru_family import BooruFamilySource
        prefixes = [c.prefix for c in SOURCE_CLASSES if issubclass(c, BooruFamilySource)]
        self.assertEqual(len(prefixes), len(set(prefixes)))


class ItemCallbackAndSkipIds(unittest.TestCase):
    """Every site: item_cb fires once per kept item, skip_ids is honoured BEFORE downloading."""

    def _check(self, site, query, handler, skip_id, expect, creds=None):
        items, urls, log, http, got = fetch(site, query, handler, creds=creds, skip={skip_id})
        self.assertEqual(len(items), expect, [m for _, m in log])
        self.assertEqual(len(got), len(items))
        self.assertNotIn(skip_id, [i.post_id for i in items])

    def test_booru_api_sites(self):
        posts = [{"id": i, "tags": f"t{i}", "file_url": f"https://img.example/{i}.jpg"} for i in (1, 2, 3)]
        h = lambda u: reply(json.dumps({"post": posts})) if "dapi" in u else reply("IMG:" + u)
        keys = {"api_key": "K", "user_id": "U"}
        for site, prefix, creds in (("safebooru", "sb_", None), ("tbib", "tb_", None), ("xbooru", "xb_", None),
                                    ("hypnohub", "hh_", None), ("gelbooru", "gb_", keys), ("rule34", "r34_", keys)):
            with self.subTest(site=site):
                self._check(site, "x", h, f"{prefix}2", 2, creds)

    def test_redgifs(self):
        gifs = [{"id": f"g{i}", "title": "t", "tags": [], "urls": {"hd": f"https://v.example/{i}.mp4"}} for i in (1, 2, 3)]
        h = lambda u: (reply(json.dumps({"token": "T"})) if "auth" in u
                       else reply(json.dumps({"gifs": gifs})) if "search" in u else reply("V:" + u))
        self._check("redgifs", "x", h, "rg_g2", 2)

    def test_freesound(self):
        snd = [{"id": i, "name": f"s{i}", "tags": [], "username": "u", "license": "https://creativecommons.org/licenses/by/4.0/",
                "previews": {"preview-hq-mp3": f"https://cdn.example/{i}.mp3"}} for i in (11, 12, 13)]
        h = lambda u: reply(json.dumps({"results": snd, "next": None})) if "search" in u else reply("A:" + u)
        self._check("freesound", "rain", h, "fs_12", 2, creds={"api_key": "K"})

    def test_erome(self):
        search = "".join(f'<a href="https://www.erome.com/a/alb{i}">x</a>' for i in (1, 2))
        album = lambda u: ('<meta property="og:title" content="A"><video><source src="https://s.example/%s.mp4"></video>'
                           '<img class="img-back" data-src="https://s.example/%s.jpg">' % ((u[-4:],) * 2))
        h = lambda u: reply(search) if "search?q=" in u else reply(album(u)) if "/a/alb" in u else reply("M:" + u)
        self._check("erome", "cap", h, "erome_alb1_0", 3)

    def test_soundgasm(self):
        prof = "".join(f'<a href="https://soundgasm.net/u/U/clip{i}">C{i}</a>' for i in (1, 2, 3))
        page = lambda u: f'<script>x="https://media.soundgasm.net/sounds/{u[-5:]}.m4a"</script>'
        h = lambda u: reply(page(u)) if "/u/U/clip" in u else reply(prof) if u.endswith("/u/U") else reply("A:" + u)
        self._check("soundgasm", "U", h, "sg_U_clip2", 2)

    def test_reddit(self):
        ns = "http://www.w3.org/2005/Atom"
        entries = "".join(f'<entry><title>P{i}</title><link href="https://www.reddit.com/r/x/comments/{i}a/p/"/>'
                          f'<content type="html">&lt;a href="https://i.redd.it/img{i}.jpg"&gt;[link]&lt;/a&gt;</content></entry>'
                          for i in (1, 2, 3))
        h = lambda u: reply(f'<feed xmlns="{ns}">{entries}</feed>') if ".rss" in u else reply("I:" + u)
        self._check("reddit", "x", h, "2a", 2)


class BooruReplies(unittest.TestCase):
    """Refusals must never be mistaken for 'no results'; the website pages are the backup."""
    RB_XML = ('<response success="false" reason="Search error: API offline because apparently it is broken and no one '
              'is able to articulate what is broken, so it will be shut off indefinitely. Feel free to browse the site '
              'the old fashioned way for now."/>')

    @staticmethod
    def website(u, ids=(41, 42)):
        if "s=list" in u:
            return reply("".join(f'<a id="p{i}" href="index.php?page=post&amp;s=view&amp;id={i}"></a>' for i in ids))
        if "s=view" in u:
            n = int(u.split("id=")[-1])
            return reply(f'<img src="https://site.example//images/ab/cd/{MD5(n)}.jpeg">')
        return reply("IMG:" + u)

    def test_refusals_fall_back_to_the_website(self):
        for name, body in (("xml error", self.RB_XML),
                           ("quoted string", '"Missing authentication. Go to api.rule34.xxx for more information"'),
                           ("plain text", "Missing authentication"),
                           ("message dict", json.dumps({"success": False, "message": "Missing authentication"})),
                           ("web page", "<!DOCTYPE html><html><body>blocked</body></html>")):
            with self.subTest(reply=name):
                h = lambda u, b=body: reply(b) if "dapi" in u else self.website(u)
                items, urls, log, http, got = fetch("safebooru", "x", h)
                self.assertEqual(len(items), 2, [m for _, m in log])
                self.assertTrue(any("web pages" in m for _, m in log))

    def test_valid_empty_replies_are_not_errors(self):
        for name, body in (("xml", '<posts count="0" offset="0"></posts>'), ("attrs", '{"@attributes":{"count":0}}'),
                           ("list", "[]"), ("empty body", "")):
            with self.subTest(reply=name):
                items, urls, log, http, got = fetch("safebooru", "x", lambda u, b=body: reply(b))
                self.assertEqual(items, [])
                self.assertFalse(any(l == "error" for l, _ in log))
                self.assertFalse(any("web pages" in m for _, m in log), "valid empty must not trigger the fallback")

    def test_xml_posts_are_parsed(self):
        xml = '<posts count="2">' + "".join(
            f'<post id="{i}" tags="a b" file_url="https://s.example/images/9/{HASH40(i)}.jpg"/>' for i in (1, 2)) + "</posts>"
        items, *_ = fetch("safebooru", "x", lambda u: reply(xml) if "dapi" in u else reply("IMG:" + u))
        self.assertEqual(len(items), 2)

    def test_api_policy_from_real_runs(self):
        h = lambda u: reply(json.dumps({"post": [{"id": 1, "file_url": "https://s.example/1.jpg"}]})) if "dapi" in u else self.website(u)
        for site, creds, expect_dapi in (("gelbooru", None, False), ("gelbooru", {"api_key": "K"}, False),
                                         ("gelbooru", {"api_key": "K", "user_id": "U"}, True),
                                         ("rule34", None, False), ("rule34", {"api_key": "K", "user_id": "U"}, True),
                                         ("realbooru", None, False), ("realbooru", {"api_key": "K", "user_id": "U"}, False),
                                         ("safebooru", None, True)):
            with self.subTest(site=site, creds=bool(creds)):
                items, urls, log, http, got = fetch(site, "x", h, creds=creds)
                self.assertEqual(any("dapi" in u for u in urls), expect_dapi)
                self.assertGreaterEqual(len(items), 1)

    def test_credentials_sent_but_never_logged(self):
        h = lambda u: reply(json.dumps({"post": [{"id": 1, "file_url": "https://s.example/1.jpg"}]})) if "dapi" in u else reply("IMG")
        items, urls, log, http, got = fetch("gelbooru", "x", h, creds={"api_key": "SECRETKEY", "user_id": "4242"})
        self.assertTrue(any("api_key=SECRETKEY" in u and "user_id=4242" in u for u in urls))
        self.assertTrue(all("SECRETKEY" not in c["url"] and "4242" not in c["url"] for c in http))

    def test_401_body_is_kept_and_site_still_works_anonymously(self):
        def h(u):
            if "dapi" in u:
                raise err(u, 401, b"Missing authentication")
            return self.website(u)
        items, urls, log, http, got = fetch("safebooru", "x", h)
        self.assertEqual(len(items), 2)
        self.assertTrue(any(c.get("status") == 401 and "Missing authentication" in c.get("body", "") for c in http))

    def test_blocked_everywhere_gives_one_clear_error(self):
        def h(u):
            if "dapi" in u:
                raise err(u, 403, b"nope")
            return reply("<!DOCTYPE html><html><title>Just a moment...</title></html>")
        items, urls, log, http, got = fetch("gelbooru", "x", h)
        errors = [m for l, m in log if l == "error"]
        self.assertEqual(items, [])
        self.assertTrue(errors and "Cloudflare" in errors[0], errors)

    def test_old_boards_without_file_url_are_rebuilt_from_directory_and_image(self):
        old = [{"id": i, "directory": "77", "image": f"h{i}.jpg", "tags": "a b"} for i in (5, 6)]
        for site in ("safebooru", "tbib", "xbooru"):
            with self.subTest(site=site):
                items, urls, *_ = fetch(site, "x", lambda u: reply(json.dumps(old)) if "dapi" in u else reply("IMG:" + u))
                self.assertEqual(len(items), 2)
                self.assertTrue(any("/images/77/h5.jpg" in u for u in urls))

    def test_skip_ids_are_checked_before_fetching_the_post_page(self):
        items, urls, *_ = fetch("realbooru", "x", lambda u: self.website(u, ids=(1, 2, 3)), skip={"rb_2"})
        self.assertEqual(len(items), 2)
        self.assertFalse(any("id=2" in u for u in urls if "s=view" in u))

    def test_a_site_that_ignores_paging_cannot_loop_forever(self):
        posts = [{"id": i, "file_url": f"https://s.example/{i}.jpg"} for i in (1, 2, 3)]
        items, urls, log, http, got = fetch("safebooru", "x",
                                            lambda u: reply(json.dumps(posts)) if "dapi" in u else reply("IMG:" + u),
                                            limit=50)
        self.assertEqual(len(items), 3)
        self.assertLess(len(urls), 20)

    def test_website_paging_advances_by_the_ids_found(self):
        """RealBooru lists 40 per page, others 42: the offset must follow what was actually found."""
        pages = {0: range(1, 41), 40: range(41, 81), 80: range(81, 86)}
        def h(u):
            if "s=list" in u:
                pid = int(u.split("pid=")[-1])
                return reply("".join(f'<a id="p{i}" href="x"></a>' for i in pages[pid]))
            return self.website(u)
        items, urls, log, http, got = fetch("realbooru", "x", h, limit=200)
        pids = [int(u.split("pid=")[-1]) for u in urls if "s=list" in u]
        self.assertEqual(pids, [0, 40, 80])
        self.assertEqual(len(items), 85)


class Redgifs(unittest.TestCase):
    VALID = {"top", "top7", "top28", "latest", "score", "trending"}   # from the API's own 400 reply

    def test_every_sort_and_quality_maps_to_a_valid_order(self):
        from sources.redgifs_source import ORDER_MAP, RedgifsSource
        self.assertLessEqual(set(ORDER_MAP.values()), self.VALID)
        self.assertEqual(set(RedgifsSource.sort_options), set(ORDER_MAP))
        for q in ("Any", "Good", "Best"):
            self.assertIn(RedgifsSource.resolve_quality(q)["sort"], ORDER_MAP)
        self.assertEqual(ORDER_MAP[RedgifsSource.default_sort], "score")

    def test_default_search_uses_order_score_like_the_website(self):
        h = lambda u: reply(json.dumps({"token": "T"})) if "auth" in u else reply(json.dumps({"gifs": []}))
        items, urls, *_ = fetch("redgifs", "cats", h)
        search = [u for u in urls if "gifs/search" in u][0]
        self.assertIn("order=score", search)
        self.assertIn("tags=Cats", search)          # Redgifs filters by official tag names ...
        self.assertIn("type=g", search)
        self.assertNotIn("search_text", search)      # ... and silently ignores free text

    def test_bad_order_reply_is_shown_in_the_log(self):
        body = b'{"error":{"code":"BadOrder","message":"Bad sorting order \\"new\\", must be one of: top, top7"}}'
        def h(u):
            if "auth" in u:
                return reply(json.dumps({"token": "T"}))
            raise err(u, 400, body)
        items, urls, log, http, got = fetch("redgifs", "x", h)
        self.assertTrue(any("BadOrder" in m for l, m in log if l == "error"))

    def test_expired_token_is_refreshed_once(self):
        state = {"tokens": 0}
        gifs = [{"id": "g1", "title": "t", "tags": [], "urls": {"hd": "https://v.example/1.mp4"}}]
        def h(u):
            if "auth" in u:
                state["tokens"] += 1
                return reply(json.dumps({"token": f"T{state['tokens']}"}))
            if "search" in u:
                if state["tokens"] < 2:
                    raise err(u, 401)
                return reply(json.dumps({"gifs": gifs}))
            return reply("V:" + u)
        items, *_ = fetch("redgifs", "x", h)
        self.assertEqual(len(items), 1)
        self.assertEqual(state["tokens"], 2)


class Netlog(unittest.TestCase):
    def call(self, fn):
        with mock.patch("time.sleep") as sleep, mock.patch.object(netlog, "_orig_urlopen", fn):
            urllib.request.urlopen = netlog._wrapped
            http = []
            netlog.begin(http)
            try:
                out = urllib.request.urlopen(urllib.request.Request("https://x.example/a?token=SECRET&user_id=42")).read()
            except Exception as ex:
                out = type(ex).__name__
            netlog.end()
        return out, http, sleep.call_count

    @staticmethod
    def flaky(times, exc):
        state = {"n": 0}
        def fn(req, timeout=15):
            state["n"] += 1
            if state["n"] <= times:
                raise exc(req.full_url) if callable(exc) else exc
            return reply("OK")
        return fn, state

    def test_transient_errors_are_retried_and_secrets_redacted(self):
        fn, st = self.flaky(2, lambda u: err(u, 503, b"busy"))
        out, http, sleeps = self.call(fn)
        self.assertEqual((out, st["n"], sleeps), (b"OK", 3, 2))
        self.assertTrue(all("SECRET" not in c["url"] and "user_id=42" not in c["url"] for c in http))
        fn, st = self.flaky(1, socket.timeout("timed out"))
        self.assertEqual(self.call(fn)[0], b"OK")

    def test_permanent_errors_are_not_retried(self):
        for name, exc in (("404", lambda u: err(u, 404)), ("429", lambda u: err(u, 429)), ("403", lambda u: err(u, 403)),
                          ("dns", urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")))):
            with self.subTest(error=name):
                fn, st = self.flaky(9, exc)
                out, http, sleeps = self.call(fn)
                self.assertEqual((st["n"], sleeps), (1, 0))

    def test_gives_up_after_two_retries(self):
        fn, st = self.flaky(9, lambda u: err(u, 500))
        self.assertEqual((self.call(fn)[0], st["n"]), ("HTTPError", 3))


class DownloadedFileSanity(unittest.TestCase):
    def test_error_pages_are_detected_but_real_media_is_not(self):
        d = tempfile.mkdtemp()
        for name, data, expect in (("h", b"<!DOCTYPE html><html>", True), ("j", b'{"error":1}', True), ("e", b"", True),
                                   ("jpg", b"\xff\xd8\xff\xe0JFIF", False), ("mp4", b"\x00\x00\x00\x18ftypmp42", False),
                                   ("png", b"\x89PNG\r\n", False), ("mp3", b"ID3\x03", False)):
            p = os.path.join(d, name)
            with open(p, "wb") as f:
                f.write(data)
            self.assertIs(looks_like_error_page(p), expect, name)


if __name__ == "__main__":
    unittest.main()

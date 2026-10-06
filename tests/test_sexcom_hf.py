"""Offline tests for Sex.com and Hentai Foundry (synthetic pages shaped like the real ones)."""
import json
import unittest
import urllib.error
from unittest import mock

from sources.sexcom_source import SexComPicsSource, parse_items
from sources.hentaifoundry_source import HentaiFoundrySource, parse_results, BLOCK_HELP
from sources.json_board import ApiError

RSC = ('self.__next_f.push([1,"...\\"items\\":[{\\"id\\":1,\\"externalId\\":111,\\"uri\\":\\"/images/pinporn/2018/04/26/1.jpg\\",'
       '\\"title\\":\\"Nice \\u0026 sunny\\",\\"width\\":8,\\"height\\":9},{\\"id\\":2,\\"externalId\\":222,'
       '\\"uri\\":\\"/images/pinporn/2018/04/27/2.jpg\\",\\"title\\":\\"two\\",\\"width\\":8,\\"height\\":9}],'
       '\\"paging\\":{\\"total\\":90,\\"numberOfPages\\":3,\\"page\\":1,\\"limit\\":40}...\\"staticPinImageDomain\\":'
       '\\"https://img.example\\"..."])')

HF = ("<div class='thumb_square'><div class=\"thumbTitle\"><a href=\"/pictures/user/bob/101/First\">First</a></div>"
      "<a class=\"thumbLink\" href=\"/pictures/user/bob/101/First\"><span title=\"First &amp; best\" class=\"thumb\" "
      "style=\"background-image: url(//thumbs.hentai-foundry.com/thumb.php?pid=101&amp;size=350)\"></span></a>"
      "<div class='ratings_box'><span class='rating lvl3' title='Nudity'>N</span></div></div>"
      "<div class='thumb_square'><div class=\"thumbTitle\"></div><a class=\"thumbLink\" "
      "href=\"/pictures/user/amy/102/Second\"><span title=\"Second\" class=\"thumb\" style=\"\"></span></a></div>"
      "<ul class=\"yiiPager\"><li class=\"next\"><a href=\"/search/index?query=x&amp;page=2\">Next</a></li></ul>")


class SexCom(unittest.TestCase):
    def test_parse_items_decodes_titles(self):
        items = parse_items(RSC)
        self.assertEqual([(i["id"], i["uri"]) for i in items],
                         [("111", "/images/pinporn/2018/04/26/1.jpg"), ("222", "/images/pinporn/2018/04/27/2.jpg")])
        self.assertEqual(items[0]["title"], "Nice & sunny")

    def test_first_page_from_html_then_api_pages(self):
        s = SexComPicsSource()
        calls = []

        def op(url, headers=None, timeout=20):
            calls.append(url)
            if "/portal/api/" in url:
                return json.dumps({"items": [{"externalId": 333, "uri": "/images/x/3.jpg", "title": "three"}]}).encode()
            return RSC.encode()
        s._open = op
        posts, nxt = s._page("cat", None)
        self.assertEqual((len(posts), nxt), (2, 2))
        self.assertTrue(posts[0]["url"].startswith("https://img.example/images/"))
        posts, nxt = s._page("cat", 2)
        self.assertEqual([p["id"] for p in posts], ["333"])
        self.assertEqual(nxt, 3)
        self.assertIn("/portal/api/pictures/search", calls[-1])
        self.assertIn("search=cat", calls[0])

    def test_api_refusal_explains_itself(self):
        s = SexComPicsSource()
        s._pages = 3

        def op(url, headers=None, timeout=20):
            raise urllib.error.HTTPError(url, 403, "no", {}, None)
        s._open = op
        with self.assertRaises(ApiError) as cm:
            s._page("cat", 2)
        self.assertIn("search API", str(cm.exception))


class HentaiFoundry(unittest.TestCase):
    def test_parse_results(self):
        posts, nxt = parse_results(HF)
        self.assertTrue(nxt)
        self.assertEqual([p["id"] for p in posts], ["101", "102"])
        self.assertEqual(posts[0]["title"], "First & best")
        self.assertIn("Nudity", posts[0]["text"])

    def test_bot_check_is_reported_not_bypassed(self):
        s = HentaiFoundrySource()

        def op(url, headers=None, timeout=20):
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
        s._open = op
        with self.assertRaises(ApiError) as cm:
            s._page("cat", None)
        self.assertIn("Cookie", str(cm.exception))
        self.assertEqual(str(cm.exception).split(" (HTTP")[0], BLOCK_HELP)

    def test_cookie_is_sent_and_picture_page_resolved(self):
        s = HentaiFoundrySource(cookie="a=b")
        self.assertEqual(s._headers()["Cookie"], "a=b")
        s._open = lambda url, headers=None, timeout=20: (
            b'<meta property="og:image" content="//pictures.hentai-foundry.com/b/bob/101/x.jpg">')
        url = s._resolve_url({"id": "101", "path": "/pictures/user/bob/101/First"}, lambda *a: None)
        self.assertEqual(url, "https://pictures.hentai-foundry.com/b/bob/101/x.jpg")

    def test_registered_and_cleaned(self):
        from sources import SOURCE_BY_ID
        from core.query_clean import clean_query
        for sid in ("sexcom_pics", "sexcom_gifs", "hentaifoundry"):
            self.assertIn(sid, SOURCE_BY_ID)
        self.assertEqual(clean_query("sexcom_pics", "https://www.sex.com/en/pics?search=big+cat"), "big cat")
        self.assertEqual(clean_query("hentaifoundry", "https://www.hentai-foundry.com/search/index?query=cat"), "cat")


class FindLookups(unittest.TestCase):
    def _with(self, handler):
        import urllib.request as ur
        return mock.patch.object(ur, "urlopen", lambda req, timeout=8: handler(req.full_url))

    def test_sexcom_count_none_and_unreachable(self):
        from tests._net import reply, err
        page = RSC.replace('numberOfPages', 'numberOfPages')
        with self._with(lambda u: reply(page.replace('\\"paging\\":{', '\\"paging\\":{'))):
            r = SexComPicsSource.suggest("cat")
        self.assertEqual(r[0]["value"], "cat")
        with self._with(lambda u: reply("<html>no items</html>")):
            self.assertEqual(SexComPicsSource.suggest("zzzz"), [])
        def boom(u):
            raise OSError("down")
        with self._with(boom):
            r = SexComPicsSource.suggest("cat")
        self.assertEqual((r[0]["value"], r[0]["count"]), ("cat", None))      # unverified but still offered

    def test_sexcom_total_is_read(self):
        from tests._net import reply
        page = RSC.replace('\\"paging\\":{\\"total\\":90', '\\"paging\\":{\\"total\\":90')
        with self._with(lambda u: reply(page)):
            self.assertEqual(SexComPicsSource.suggest("cat")[0]["count"], 90)

    def test_wallhaven_count_and_fallback(self):
        from tests._net import reply
        from sources.wallhaven_source import WallhavenSource
        with self._with(lambda u: reply(json.dumps({"meta": {"total": 1234}}))):
            r = WallhavenSource.suggest("cat")
        self.assertEqual((r[0]["count"], r[0]["nofilter"]), (1234, True))
        with self._with(lambda u: reply(json.dumps({"meta": {"total": 0}}))):
            self.assertEqual(WallhavenSource.suggest("cat")[0]["count"], None)   # NSFW may exist: still offered
        with self._with(lambda u: reply("<html>")):
            self.assertEqual(len(WallhavenSource.suggest("cat")), 1)

    def test_erome_and_soundgasm_verify_something_exists(self):
        from tests._net import reply, err
        from sources.erome_source import EromeSource
        from sources.soundgasm_source import SoundgasmSource
        with self._with(lambda u: reply('<a href="https://www.erome.com/a/AbC123">x</a>')):
            self.assertEqual(EromeSource.suggest("cosplay")[0]["value"], "cosplay")
        with self._with(lambda u: reply("<html>nothing</html>")):
            self.assertEqual(EromeSource.suggest("zzzz"), [])
        page = '<a href="https://soundgasm.net/u/Amy/one">One</a><a href="https://soundgasm.net/u/Amy/two">Two</a>'
        with self._with(lambda u: reply(page)):
            r = SoundgasmSource.suggest("Amy")
        self.assertEqual((r[0]["count"], r[0]["nofilter"]), (2, True))

        def nf(u):
            raise err(u, 404)
        with self._with(nf):
            self.assertEqual(SoundgasmSource.suggest("nobody"), [])
        self.assertEqual(SoundgasmSource.suggest("two words"), [])

    def test_small_counts_not_hidden_for_nofilter_entries(self):
        from core.collector import suggest_all
        from sources import SOURCE_BY_ID
        from sources.base import Source

        class Tiny(Source):
            id, label = "tiny", "Tiny"

            @classmethod
            def suggest(cls, q):
                return [{"value": "keep", "count": 5, "nofilter": True}, {"value": "drop", "count": 5}]
        with mock.patch.dict(SOURCE_BY_ID, {"tiny": Tiny}):
            out = suggest_all("x", source_ids=["tiny"], min_count=100)
        self.assertEqual([m["value"] for m in out], ["keep"])


if __name__ == "__main__":
    unittest.main()

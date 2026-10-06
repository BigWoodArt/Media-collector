"""Offline tests for the JSON-board sources: python -m unittest tests.test_new_sources"""
import json
import unittest

from tests._net import fetch, reply, err
from core.safety import is_blocked, query_blocked


def img(u):
    return reply(b"\x89PNG-" + u.encode())


class Guard(unittest.TestCase):
    def test_guard(self):
        self.assertTrue(is_blocked("cat_ears loli"))
        self.assertTrue(is_blocked(["solo", "toddler"]))
        self.assertFalse(is_blocked("cat_ears solo cubism"))
        self.assertTrue(query_blocked("shota"))


class Boards(unittest.TestCase):
    def run_site(self, site, handler, query="cats", **kw):
        return fetch(site, query, handler, **kw)

    def test_e621(self):
        data = {"posts": [
            {"id": 1, "file": {"url": "https://s/1.jpg"}, "tags": {"general": ["cat"], "species": []}},
            {"id": 2, "file": {"url": None}, "tags": {"general": ["cat"]}},
            {"id": 3, "file": {"url": "https://s/3.png"}, "tags": {"general": ["cub"]}}]}
        h = lambda u: reply(json.dumps(data)) if "posts.json" in u else img(u)
        items, urls, log, http, got = self.run_site("e621", h)
        self.assertEqual([i.post_id for i in items], ["e6_1"])
        self.assertEqual(len(got), 1)

    def test_e621_sends_non_browser_agent(self):
        seen = []
        import urllib.request as ur
        orig = ur.Request
        def spy(url, *a, **k):
            seen.append((k.get("headers") or {}).get("User-Agent", ""))
            return orig(url, *a, **k)
        h = lambda u: reply(json.dumps({"posts": []}))
        from unittest import mock
        with mock.patch("urllib.request.Request", spy):
            self.run_site("e621", h)
        self.assertTrue(seen and all("Mozilla" not in s and "MediaCollector" in s for s in seen), seen)

    def test_danbooru_and_tag_limit_hint(self):
        data = [{"id": 5, "file_url": "https://d/5.jpg", "tag_string": "cat_ears solo"},
                {"id": 6, "file_url": "https://d/6.jpg", "tag_string": "loli"}]
        h = lambda u: reply(json.dumps(data)) if "posts.json" in u else img(u)
        items, *_ = self.run_site("danbooru", h)
        self.assertEqual([i.post_id for i in items], ["db_5"])
        bad = lambda u: reply(json.dumps({"success": False, "message": "You cannot search for more than 2 tags"}))
        items, urls, log, *_ = self.run_site("danbooru", bad)
        self.assertEqual(items, [])
        self.assertTrue(any("2 tags" in m for _, m in log))

    def test_moebooru_sites(self):
        data = [{"id": 9, "file_url": "https://m/9.jpg", "tags": "cat_ears"}]
        for site, pre in (("yandere", "yd_"), ("konachan", "kc_")):
            h = lambda u: reply(json.dumps(data)) if "post.json" in u else img(u)
            items, *_ = self.run_site(site, h)
            self.assertEqual([i.post_id for i in items], [pre + "9"])

    def test_derpibooru(self):
        data = {"images": [{"id": 7, "representations": {"full": "https://p/7.png"}, "tags": ["safe"]}]}
        h = lambda u: reply(json.dumps(data)) if "search/images" in u else img(u)
        items, urls, *_ = self.run_site("derpibooru", h)
        self.assertEqual([i.post_id for i in items], ["dp_7"])
        self.assertTrue(any("filter_id=56027" in u for u in urls))

    def test_wallhaven_paging_and_key(self):
        pages = {"1": {"data": [{"id": "a1", "path": "https://w/a1.jpg"}], "meta": {"current_page": 1, "last_page": 2}},
                 "2": {"data": [{"id": "b2", "path": "https://w/b2.jpg"}], "meta": {"current_page": 2, "last_page": 2}}}
        def h(u):
            if "api/v1/search" in u:
                return reply(json.dumps(pages["2" if "page=2" in u else "1"]))
            return img(u)
        items, urls, *_ = self.run_site("wallhaven", h, limit=5, creds={"api_key": "K"})
        self.assertEqual([i.post_id for i in items], ["wh_a1", "wh_b2"])
        self.assertTrue(any("purity=011" in u for u in urls))

    def test_civitai_user_cursor_and_prompt_guard(self):
        pg1 = {"items": [{"id": 1, "url": "https://c/1.jpeg", "meta": {"prompt": "a cat"}},
                         {"id": 2, "url": "https://c/2.jpeg", "meta": {"prompt": "young girl"}}],
               "metadata": {"nextCursor": "abc"}}
        pg2 = {"items": [{"id": 3, "url": "https://c/3.jpeg", "meta": None}], "metadata": {}}
        def h(u):
            if "api/v1/images" in u:
                return reply(json.dumps(pg2 if "cursor=abc" in u else pg1))
            return img(u)
        items, urls, *_ = self.run_site("civitai", h, query="user:someone", limit=5, creds={"api_key": "K"})
        self.assertEqual([i.post_id for i in items], ["cv_1", "cv_3"])
        self.assertTrue(any("username=someone" in u for u in urls))

    def test_civitai_model_name_lookup(self):
        def h(u):
            if "api/v1/models" in u:
                return reply(json.dumps({"items": [{"id": 42}]}))
            if "api/v1/images" in u:
                return reply(json.dumps({"items": [{"id": 8, "url": "https://c/8.jpeg"}], "metadata": {}}))
            return img(u)
        items, urls, *_ = self.run_site("civitai", h, query="some model", creds={"api_key": "K"})
        self.assertEqual(len(items), 1)
        self.assertTrue(any("modelId=42" in u for u in urls))

    def test_civitai_requires_key(self):
        items, urls, log, *_ = self.run_site("civitai", lambda u: reply("{}"), query="user:x")
        self.assertEqual((items, urls), ([], []))
        self.assertTrue(any("API key" in m for _, m in log))

    def test_lemmy(self):
        data = {"posts": [{"post": {"id": 1, "name": "nice", "url": "https://l/1.jpg", "url_content_type": "image/jpeg"}},
                          {"post": {"id": 2, "name": "article", "url": "https://news/x", "url_content_type": "text/html"}}]}
        h = lambda u: reply(json.dumps(data)) if "post/list" in u else img(u)
        items, urls, *_ = self.run_site("lemmy", h, query="cats@lemmy.world")
        self.assertEqual([i.post_id for i in items], ["lm_1"])

    def test_blocked_query_makes_no_requests(self):
        items, urls, log, *_ = self.run_site("e621", lambda u: reply("{}"), query="cub")
        self.assertEqual((items, urls), ([], []))

    def test_skip_ids_honoured_before_download(self):
        data = [{"id": 5, "file_url": "https://d/5.jpg", "tag_string": "a"}]
        h = lambda u: reply(json.dumps(data)) if "posts.json" in u else img(u)
        items, urls, *_ = fetch("danbooru", "a", h, skip={"db_5"})
        self.assertEqual(items, [])
        self.assertFalse(any(u.endswith("5.jpg") for u in urls))

    def test_http_failure_is_logged_not_raised(self):
        def h(u):
            raise err(u, 403)
        items, urls, log, *_ = self.run_site("e621", h)
        self.assertEqual(items, [])
        self.assertTrue(any("403" in m for _, m in log))


if __name__ == "__main__":
    unittest.main()

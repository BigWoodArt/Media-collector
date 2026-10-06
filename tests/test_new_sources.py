"""Offline tests for the JSON-board sources: python -m unittest tests.test_new_sources"""
import json
import unittest

from unittest import mock

from tests._net import fetch, reply, err
from sources import SOURCE_BY_ID, SOURCE_CLASSES
from sources.civitai_source import CivitaiSource
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

    def test_civitai_is_disabled_in_the_app(self):
        self.assertNotIn("civitai", SOURCE_BY_ID)
        self.assertNotIn(CivitaiSource, SOURCE_CLASSES)

    @mock.patch.dict(SOURCE_BY_ID, {"civitai": CivitaiSource})
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

    @mock.patch.dict(SOURCE_BY_ID, {"civitai": CivitaiSource})
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


class Suggest(unittest.TestCase):
    """suggest() lookups, with the network faked at urlopen."""

    def _run(self, cls, handler, query):
        import urllib.request as ur
        def fake(req, timeout=8):
            return handler(getattr(req, "full_url", str(req)))
        with mock.patch.object(ur, "urlopen", fake):
            return cls.suggest(query)

    def test_reddit_exact_match_comes_first_then_search(self):
        from sources.reddit_source import RedditSource
        def h(u):
            if "/r/catears/about.json" in u:
                return reply(json.dumps({"kind": "t5", "data": {"display_name": "catears", "subscribers": 900}}))
            if "/r/cat_ears/about.json" in u:
                raise err(u, 404)
            if "subreddits/search" in u:
                return reply(json.dumps({"data": {"children": [
                    {"data": {"display_name": "catgirls", "subscribers": 400000}},
                    {"data": {"display_name": "CatEars", "subscribers": 900}}]}}))
            raise err(u, 404)
        r = self._run(RedditSource, h, "cat ears")
        self.assertEqual([m["value"] for m in r], ["catears", "catgirls"])   # exact first, deduped

    def test_reddit_no_such_subreddit_falls_back_to_search(self):
        from sources.reddit_source import RedditSource
        def h(u):
            if "about.json" in u:
                raise err(u, 404)
            return reply(json.dumps({"data": {"children": [{"data": {"display_name": "x", "subscribers": 5}}]}}))
        self.assertEqual([m["value"] for m in self._run(RedditSource, h, "zzzz")], ["x"])

    def test_redgifs_tag_suggestions(self):
        from sources.redgifs_source import RedgifsSource
        def h(u):
            if "auth/temporary" in u:
                return reply(json.dumps({"token": "T"}))
            if "search/suggest" in u:
                return reply(json.dumps([{"text": "Hypno", "gifs": 5200}, {"text": "Hypnosis", "gifs": 800}]))
            raise err(u, 404)
        r = self._run(RedgifsSource, h, "hypno")
        self.assertEqual([(m["value"], m["count"]) for m in r], [("Hypno", 5200), ("Hypnosis", 800)])

    def test_suggest_never_raises_when_the_site_is_down(self):
        from sources.redgifs_source import RedgifsSource
        from sources.reddit_source import RedditSource
        def h(u):
            raise err(u, 503)
        self.assertEqual(self._run(RedgifsSource, h, "x"), [])
        self.assertEqual(self._run(RedditSource, h, "x"), [])


class BooruSuggestAndWait(unittest.TestCase):
    def test_booru_suggest_tries_routes_until_one_answers(self):
        import urllib.request as ur
        from sources.hypnohub_source import HypnohubSource
        def fake(req, timeout=8):
            u = req.full_url
            if "/tag/index.json" in u:
                return reply(json.dumps([{"name": "cat_ears", "count": 321, "type": 0}]))
            raise err(u, 404)
        with mock.patch.object(ur, "urlopen", fake):
            r = HypnohubSource.suggest("cat ears")
        self.assertEqual([(m["value"], m["count"]) for m in r], [("cat_ears", 321)])

    def test_booru_suggest_parses_label_counts_and_never_raises(self):
        import urllib.request as ur
        from sources.booru_extra_sources import Rule34Source
        def ok(req, timeout=8):
            return reply(json.dumps([{"label": "cat_ears (1500)", "value": "cat_ears"}]))
        with mock.patch.object(ur, "urlopen", ok):
            self.assertEqual(Rule34Source.suggest("cat")[0]["count"], 1500)
        def boom(req, timeout=8):
            raise OSError("down")
        with mock.patch.object(ur, "urlopen", boom):
            self.assertEqual(Rule34Source.suggest("cat"), [])

    def test_reddit_rate_limiter_announces_waits(self):
        from sources.reddit_source import RateLimiter
        seen = []
        rl = RateLimiter(min_interval=1.0)
        rl.notify = lambda m, lvl: seen.append((m, lvl))
        with mock.patch("sources.reddit_source.time.sleep"):
            rl.last = __import__("time").time()
            rl.wait()
        self.assertEqual(seen[0][1], "wait")
        self.assertTrue(seen[0][0].startswith("WAIT|"))

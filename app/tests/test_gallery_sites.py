"""PornPics + Babehub: search -> galleries -> every picture, with page layouts copied from the real sites."""
import unittest

from tests._net import fetch, reply, err


def pp_gallery(gid, n, rating="95", tags=("Blonde", "Solo"), title="Nice set"):
    pics = "".join(f"<li class='thumbwook'><a class='rel-link' href='https://cdni.pornpics.com/1280/1/22/{gid}/{gid}_{i:03d}_ab{i}.jpg' "
                   f"data-size='1280x1920'><img src='x'></a></li>" for i in range(1, n + 1))
    tg = "".join(f"<a href='/tags/{t.lower()}/' target=_self title='{t} Pics' ><span>{t}</span></a>" for t in tags)
    return (f"<html><title>{title} - PornPics.com</title><h1>{title}</h1>"
            f'<div class="gallery-info__item tags"><span class="gallery-info__title">Categories:</span></div>'
            f'<div class="gallery-info__item tags"><span class="gallery-info__title">Tags:</span><div>{tg}</div></div>'
            f'<div class="gallery-info__item"><span class="info-rate"><span class="rate-count">{rating}%</span></span></div>'
            f"<ul id='tiles'>{pics}</ul></html>")


def pp_listing(gids):
    return "<ul>" + "".join(f'<li><a class="rel-link" href="https://www.pornpics.com/galleries/some-set-{g}/">x</a></li>'
                            for g in gids) + "</ul>"


def bh_gallery(gid, n, likes=180, tags=("Blonde", "Petite"), title="Set title"):
    pics = "".join(f'<li><a data-fancybox="images" data-srcset="https://cdn.babehub.com/c/{gid}_{i}_800.jpg 800w" '
                   f'href="https://cdn.babehub.com/c/{gid}_{i}_1200.jpg" data-width="1200"><img src="y"></a></li>'
                   for i in range(1, n + 1))
    tg = "".join(f'<a href="https://www.babehub.com/tag/{t.lower()}/" class="visible-tag">{t}</a> ' for t in tags)
    return (f"<html><h1>{title}</h1><p class=\"link-btn scroll\"><a class=\"overlay-b\" href=\"https://www.babehub.com/model/jane/\">Jane</a>"
            f"{tg}</p><ul>{pics}</ul><span id=\"thelike\">{likes}</span></html>")


def bh_listing(gids):
    return ('<a href="https://www.babehub.com/tag/blonde/">tag</a><ul class="list-gallery">'
            + "".join(f'<li><a href="https://www.babehub.com/some-title-{g}/">x</a></li>' for g in gids) + "</ul>")


class PornPics(unittest.TestCase):
    def handler(self, pages=None, galleries=None):
        pages = pages or {}
        galleries = galleries or {1001: (3, "95"), 1002: (2, "60")}

        def h(u):
            if "/galleries/" in u:
                gid = int(u.rstrip("/").rsplit("-", 1)[1])
                n, rating = galleries[gid]
                return reply(pp_gallery(gid, n, rating))
            if "cdni.pornpics.com" in u:
                return reply("IMG:" + u)
            for key, body in sorted(pages.items(), key=lambda kv: -len(kv[0])):
                if key in u:
                    return reply(body)
            return reply(pp_listing([]))
        return h

    def test_downloads_every_picture_in_each_gallery(self):
        h = self.handler({"?q=blonde": pp_listing([1001, 1002])})
        items, urls, log, http, got = fetch("pornpics", "blonde", h, limit=50)
        self.assertEqual(len(items), 5)
        self.assertTrue(all(i.post_id.startswith("pnp_") for i in items))
        self.assertTrue(any("/?q=blonde" in u for u in urls))

    def test_limit_counts_pictures(self):
        h = self.handler({"?q=blonde": pp_listing([1001, 1002])})
        items, *_ = fetch("pornpics", "blonde", h, limit=4)
        self.assertEqual(len(items), 4)

    def test_min_rating_skips_whole_galleries(self):
        h = self.handler({"?q=blonde": pp_listing([1001, 1002])})
        items, urls, log, http, got = fetch("pornpics", "blonde score:>=80", h, limit=50)
        self.assertEqual(len(items), 3)
        self.assertTrue(any("skipped a gallery rated 60" in m for _, m in log))
        self.assertFalse(any("score" in u for u in urls))

    def test_skip_ids_and_single_gallery_link(self):
        h = self.handler()
        items, *_ = fetch("pornpics", "https://www.pornpics.com/galleries/some-set-1001/", h, limit=50,
                          skip={"pnp_1001_1001_001_ab1"})
        self.assertEqual(len(items), 2)

    def test_next_page_found_by_trying_the_usual_addresses(self):
        pages = {"/?q=blonde": pp_listing([1001]), "/?q=blonde&limit=20&offset=20": pp_listing([1002, 1001])}
        h = self.handler(pages)
        items, urls, log, http, got = fetch("pornpics", "blonde", h, limit=50)
        self.assertEqual(len(items), 5)                     # 1001 once, 1002 once
        self.assertTrue(any("page 2" in m for _, m in log))

    def test_runs_out_cleanly(self):
        h = self.handler({"?q=blonde": pp_listing([1001])})
        items, urls, log, http, got = fetch("pornpics", "blonde", h, limit=50)
        self.assertEqual(len(items), 3)
        self.assertTrue(any("search is used up" in m for _, m in log))

    def test_tags_are_read_and_the_guard_applies(self):
        def h(u):
            if "/galleries/" in u:
                return reply(pp_gallery(1001, 2, tags=("Blonde", "Underage")))
            return reply(pp_listing([1001])) if "q=" in u else reply("IMG" + u)
        items, *_ = fetch("pornpics", "blonde", h, limit=10)
        self.assertEqual(items, [])                          # a blocked tag keeps the gallery out

    def test_search_failure_is_logged(self):
        def h(u):
            raise err(u, 503)
        items, urls, log, http, got = fetch("pornpics", "blonde", h)
        self.assertEqual(items, [])
        self.assertTrue(any(l == "error" for l, _ in log))


class Babehub(unittest.TestCase):
    def handler(self, pages):
        def h(u):
            if "cdn.babehub.com" in u:
                return reply("IMG:" + u)
            gid = u.rstrip("/").rsplit("-", 1)[-1]
            if u.rstrip("/").split("/")[-1].startswith("some-title-"):
                return reply(bh_gallery(gid, 2, likes=int(gid) % 1000))
            for key, body in sorted(pages.items(), key=lambda kv: -len(kv[0])):
                if key in u:
                    return reply(body)
            return reply(bh_listing([]))
        return h

    def test_pictures_and_tag_links_are_not_mistaken_for_galleries(self):
        h = self.handler({"/tag/blonde/": bh_listing([1500, 1600])})
        items, urls, log, http, got = fetch("babehub", "blonde", h, limit=50)
        self.assertEqual(len(items), 4)
        self.assertTrue(all(i.post_id.startswith("bbh_") for i in items))
        self.assertTrue(all(u.startswith("https://www.babehub.com/tag/blonde/") for u in urls if "/tag/" in u))
        self.assertEqual(sum("some-title-" in u for u in urls), 2)

    def test_min_likes(self):
        h = self.handler({"/tag/blonde/": bh_listing([1500, 1600])})        # likes = 500 and 600
        items, *_ = fetch("babehub", "blonde score:>=550", h, limit=50)
        self.assertEqual(len(items), 2)

    def test_page_two_uses_page_path(self):
        h = self.handler({"/tag/blonde/": bh_listing([1500]), "/tag/blonde/sort/popular/mpage/2/": bh_listing([1600])})
        items, urls, log, http, got = fetch("babehub", "blonde", h, limit=50)
        self.assertEqual(len(items), 4)

    def test_randomize_still_downloads_everything(self):
        h = self.handler({"/tag/blonde/": bh_listing([1500, 1600, 1700])})
        items, *_ = fetch("babehub", "blonde", h, limit=50, randomize=True)
        self.assertEqual(len(items), 6)


    def test_unknown_tag_falls_back_to_model(self):
        h = self.handler({"/model/jane-doe/": bh_listing([1500])})
        def h2(u):
            if "/tag/jane-doe/" in u:
                raise OSError("404")
            return h(u)
        items, *_ = fetch("babehub", "Jane Doe", h2, limit=50)
        self.assertEqual(len(items), 2)


class FindLists(unittest.TestCase):
    def run_suggest(self, sid, listing):
        from unittest import mock
        from sources import SOURCE_BY_ID
        cls = SOURCE_BY_ID[sid]
        with mock.patch.object(cls, "_get_text", lambda self, url: listing):
            return cls.suggest("blonde")

    def test_pornpics_find(self):
        page = pp_listing([1001, 1002]) + "<a href='/tags/blonde-teen/'>x</a><a href='/tags/brunette/'>y</a>"
        r = self.run_suggest("pornpics", page)
        vals = [m["value"] for m in r]
        self.assertEqual(vals[0], "blonde")
        self.assertIn("https://www.pornpics.com/tags/blonde-teen/", vals)
        self.assertNotIn("https://www.pornpics.com/tags/brunette/", vals)
        self.assertEqual(sum(m["label"].endswith("(gallery)") for m in r), 2)

    def test_babehub_find_lists_tags_models_and_galleries(self):
        from unittest import mock
        from sources import SOURCE_BY_ID
        cls = SOURCE_BY_ID["babehub"]
        tags = ('<li><a href="https://www.babehub.com/tag/blonde/"><span>Blonde <small>(49408)</small></span></a></li>'
                '<li><a href="https://www.babehub.com/tag/blonde-teen/"><span>Blonde Teen <small>(900)</small></span></a></li>'
                '<li><a href="https://www.babehub.com/tag/brunette/"><span>Brunette <small>(5)</small></span></a></li>')
        models = '<a href="https://www.babehub.com/model/blonde-jane/"><span>Blonde Jane <small>(12)</small></span></a>'

        def get(self, url):
            if url.endswith("/tags/"):
                return tags
            if url.endswith("/models/"):
                return models
            if url.endswith("/channels/"):
                return ""
            return bh_listing([1500, 1600])
        with mock.patch.object(cls, "_get_text", get):
            r = cls.suggest("blonde")
        vals = [m["value"] for m in r]
        self.assertEqual(vals[:3], ["https://www.babehub.com/tag/blonde/", "https://www.babehub.com/tag/blonde-teen/",
                                    "https://www.babehub.com/model/blonde-jane/"])
        self.assertEqual(r[0]["count"], 49408)
        self.assertNotIn("https://www.babehub.com/tag/brunette/", vals)
        self.assertEqual(sum(m["label"].endswith("(gallery)") for m in r), 2)

    def test_nothing_listed_gives_nothing(self):
        self.assertEqual(self.run_suggest("pornpics", "<html></html>"), [])

    def test_has_lookup(self):
        from sources import SOURCE_CLASSES
        from core.collector import has_lookup
        self.assertTrue(all(has_lookup(c) for c in SOURCE_CLASSES if c.id in ("pornpics", "babehub")))


class Registered(unittest.TestCase):
    def test_in_every_list(self):
        from sources import SOURCE_BY_ID, grouped_sources
        listed = [c.id for _g, cs in grouped_sources() for c in cs]
        for sid in ("pornpics", "babehub"):
            self.assertIn(sid, SOURCE_BY_ID)
            self.assertIn(sid, listed)
        self.assertEqual(SOURCE_BY_ID["pornpics"].resolve("site", "80"), {"query_suffix": "score:>=80"})


if __name__ == "__main__":
    unittest.main()

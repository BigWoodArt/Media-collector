import os, tempfile, threading, unittest
from unittest import mock
from sources.pmvhaven_source import PmvHavenSource
from sources.hypnotube_source import HypnoTubeSource

CARD = ('<div class="item-inner-col inner-col"> <a href="https://hypnotube.com/video/hitomi-spiral-93485.html" title="Hitomi Spiral">'
        ' <span class="image"><img src="x.jpg"><span class="time">00:55</span> <span class="quality"> '
        '<span class="quality-icon q-hd">HD</span> </span></span> <span class="item-info"><span class="title"> Hitomi </span>'
        '<span class="item-stats"><span class="s-elem s-e-rate"><span class="icon i-thumbs-up"></span> '
        '<span class="sub-desc">73%</span></span><span class="s-elem s-e-views"><span class="sub-desc">15516</span></span>'
        '</span></span></a></div>')
CARD2 = CARD.replace("hitomi-spiral-93485", "other-1").replace("73%", "40%").replace("HD<", "SD<").replace("Hitomi Spiral", "Other")


def run(src, query, **kw):
    out = tempfile.mkdtemp()
    logs = []
    items = src.fetch(query, kw.get("limit", 5), kw.get("sort"), None, out, lambda m, l="info": logs.append(m),
                      lambda *a: None, threading.Event(), item_cb=lambda i: None)
    return items, logs


class Pmv(unittest.TestCase):
    def test_parse_modes(self):
        s = PmvHavenSource()
        self.assertEqual(s._parse("tag:big ass minheight:1080"), ("tag", "big ass", {"minheight": 1080}))
        self.assertEqual(s._parse("creator:Infinite")[:2], ("creator", "Infinite"))
        self.assertEqual(s._parse("spiral")[:2], ("search", "spiral"))
        self.assertEqual(s._parse("")[0], "browse")

    def test_tag_list_downloads_video(self):
        s = PmvHavenSource()
        urls = []
        def gj(url):
            urls.append(url)
            return {"videos": [{"_id": "a1", "title": "T", "videoUrl": "https://c.example/v.mp4", "tags": ["x"]}],
                    "pagination": {"hasNext": False, "total": 1}}
        s._get_json = gj
        s._open = lambda url, headers=None, timeout=20: b"\x00\x00\x00\x18ftypmp42" + b"1" * 50
        items, _ = run(s, "tag:Trans minrating:85")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].media_type, "video")
        self.assertEqual(items[0].post_id, "pmv_a1")
        self.assertIn("tags=Trans", urls[0]); self.assertIn("minRating=85", urls[0])
        self.assertIn("sort=-uploadDate", urls[0])

    def test_keyword_rows_without_file_link_are_looked_up(self):
        s = PmvHavenSource()
        def gj(url):
            if "/api/videos/search" in url:
                return {"videos": [{"_id": "z9", "title": "S", "tags": []}], "pagination": {"total": 1, "hasNext": False}}
            return {"data": {"videoUrl": "https://c.example/z.mp4", "tags": ["x"]}}
        s._get_json = gj
        s._open = lambda url, headers=None, timeout=20: b"\x00\x00\x00\x18ftypmp42" + b"2" * 50
        items, _ = run(s, "spiral")
        self.assertEqual([i.post_id for i in items], ["pmv_z9"])

    def test_keyword_uses_search_endpoint(self):
        s = PmvHavenSource()
        urls = []
        s._get_json = lambda url: (urls.append(url), {"videos": [], "total": 0})[1]
        run(s, "spiral")
        self.assertIn("/api/videos/search?q=spiral", urls[0])


class Hypno(unittest.TestCase):
    def test_cards_and_filters(self):
        posts = HypnoTubeSource._cards(CARD + CARD2)
        self.assertTrue(all(p["url"] for p in posts)); self.assertEqual([(p["id"], p["hd"], p["rating"]) for p in posts], [("93485", True, 73), ("1", False, 40)])
        s = HypnoTubeSource()
        s._search_html = lambda term, sort, page: CARD + CARD2
        got, nxt = s._page("spiral hd:1 minrating:70", None)
        self.assertEqual([p["id"] for p in got], ["93485"])
        self.assertIsNone(nxt)

    def test_pages_on_when_filter_empties_page(self):
        s = HypnoTubeSource()
        pages = {1: CARD2 + '<a href="page2.html">2</a> page2.html', 2: CARD}
        s._search_html = lambda term, sort, page: pages[page]
        got, nxt = s._page("spiral minrating:70", None)
        self.assertEqual([p["id"] for p in got], ["93485"])

    def test_resolve_picks_biggest_source_and_guards(self):
        s = HypnoTubeSource()
        page = ('<meta name="keywords" content="spiral, edit"><source src="https://m.example/a.mp4?token=1&amp;expires=2" '
                'type="video/mp4" sizes="480"><source src="https://m.example/b.mp4?x=1" sizes="720">')
        s._get_text = lambda url, data=None, timeout=20: page
        self.assertEqual(s._resolve_url({"id": "1", "page": "p"}, lambda *a: None), "https://m.example/b.mp4?x=1")

    def test_channel_validation(self):
        s = HypnoTubeSource()
        with self.assertRaises(Exception):
            s._page("channel:bad", None)


if __name__ == "__main__":
    unittest.main()


class Groups(unittest.TestCase):
    def test_every_site_listed_once(self):
        import sources
        ids = [c.id for _, members in sources.grouped_sources() for c in members]
        self.assertEqual(sorted(ids), sorted(c.id for c in sources.SOURCE_CLASSES))
        self.assertEqual(len(ids), len(set(ids)))

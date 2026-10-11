import os, tempfile, unittest
from core.collector import Pick, _settle, CombinedStop
import threading


class Requests(unittest.TestCase):
    def test_same_source_twice(self):
        a = Pick("reddit", "cats", order="new")
        b = Pick("reddit", "cats", order="top_month")
        self.assertNotEqual(a.key(), b.key())

    def test_prefix(self):
        d = tempfile.mkdtemp()
        f = os.path.join(d, "xyz.jpg"); open(f, "wb").write(b"1")
        out = _settle(f, d, "reddit")
        self.assertEqual(os.path.basename(out), "reddit_xyz.jpg")
        st = tempfile.mkdtemp()
        g = os.path.join(st, "reddit_abc.jpg"); open(g, "wb").write(b"1")
        self.assertEqual(os.path.basename(_settle(g, d, "reddit")), "reddit_abc.jpg")

    def test_skip_source_event(self):
        e = threading.Event(); k = threading.Event()
        c = CombinedStop(e, k); self.assertFalse(c.is_set())
        k.set(); self.assertTrue(c.is_set())

    def test_reddit_throttle_hosts(self):
        from sources.reddit_source import RedditSource
        s = RedditSource.__new__(RedditSource)
        calls = []
        class R:
            def wait(self): calls.append(1)
        s.rate_limiter = R()
        s._throttle("https://v.redd.it/a.mp4"); self.assertEqual(calls, [])
        s._throttle("https://www.reddit.com/r/x/.rss"); self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()


class RedditThumbs(unittest.TestCase):
    def cands(self, link):
        from sources.reddit_source import RedditSource
        s = RedditSource.__new__(RedditSource)
        s.resolve_redgifs = lambda *a: None          # lookup failed
        html = f'<a href="{link}">[link]</a> <img src="https://b.thumbs.redditmedia.com/t.jpg">'
        return s.build_candidates({"content_html": html, "link": "https://www.reddit.com/r/x/comments/1/"})

    def test_video_and_page_links_get_no_thumbnail(self):
        for link in ("https://www.redgifs.com/watch/abc", "https://v.redd.it/abc", "https://streamable.com/x",
                     "https://youtu.be/x", "https://example.com/article", "https://x.com/v.mp4"):
            self.assertFalse([c for c in self.cands(link) if c[3] == "image"], link)

    def test_image_links_keep_thumbnail_fallback(self):
        self.assertTrue(self.cands("https://i.redd.it/a.jpg"))
        self.assertTrue(self.cands("https://imgur.com/abc"))

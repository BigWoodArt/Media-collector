import unittest
from sources.reddit_source import RedditSource


def entry(img, link="https://www.reddit.com/r/x/comments/abc/t/", target=None):
    t = target or link
    return {"title": "t", "link": link,
            "content_html": f'<img src="{img}"> <a href="{t}">[link]</a>'}


class RedditImageRules(unittest.TestCase):
    def setUp(self):
        self.r = RedditSource()

    def test_video_preview_not_a_candidate(self):
        e = entry("https://external-preview.redd.it/a.jpg?x=1", target="https://www.redgifs.com/watch/foo")
        self.assertEqual([c for c in self.r.build_candidates(e) if c[3] == "image"], [])

    def test_unupgradable_preview_dropped(self):
        e = entry("https://preview.redd.it/a.jpg?width=140")
        imgs = [c for c in self.r.build_candidates(e) if c[3] == "image"]
        self.assertTrue(all("i.redd.it" in c[0] for c in imgs))

    def test_real_image_kept(self):
        e = entry("https://i.redd.it/a.jpg", target="https://i.redd.it/a.jpg")
        self.assertTrue(any(c[3] == "image" for c in self.r.build_candidates(e)))

    def test_too_small(self):
        import io
        from PIL import Image
        def png(n):
            b = io.BytesIO(); Image.new("RGB", (n, n)).save(b, "PNG"); return b.getvalue()
        self.assertTrue(RedditSource.too_small(png(120)))
        self.assertFalse(RedditSource.too_small(png(800)))


if __name__ == "__main__":
    unittest.main()


class RedditGallery(unittest.TestCase):
    DATA = [{"data": {"children": [{"data": {
        "gallery_data": {"items": [{"media_id": "b2"}, {"media_id": "a1"}, {"media_id": "z9"}]},
        "media_metadata": {"a1": {"status": "valid", "m": "image/png"},
                           "b2": {"status": "valid", "m": "image/jpg"},
                           "z9": {"status": "failed"}}}}]}}]

    def test_order_and_urls(self):
        self.assertEqual(RedditSource.parse_gallery(self.DATA),
                         [("https://i.redd.it/b2.jpg", ".jpg"), ("https://i.redd.it/a1.png", ".png")])

    def test_not_a_gallery(self):
        self.assertEqual(RedditSource.parse_gallery([{"data": {"children": [{"data": {}}]}}]), [])
        self.assertEqual(RedditSource.parse_gallery(None), [])

    def test_fetch_downloads_every_photo(self):
        import tempfile, threading
        r = RedditSource()
        r.rate_limiter.min_interval = 0
        r.http_get = lambda *a, **k: "<feed/>"
        r.parse_feed = lambda *a: [{"title": "Album", "link": "https://www.reddit.com/r/x/comments/abc/t/",
            "content_html": '<img src="https://preview.redd.it/b2.jpg"> <a href="https://www.reddit.com/gallery/abc">[link]</a>'}]
        r.resolve_gallery = lambda pid, log: RedditSource.parse_gallery(self.DATA)
        r.too_small = staticmethod(lambda c: False)
        r.http_get_bytes = lambda url, referer=None: url.encode()
        with tempfile.TemporaryDirectory() as d:
            out = r.fetch("x", 10, "New", "month", d, lambda *a: None, lambda *a: None, threading.Event())
        self.assertEqual(len(out), 2)

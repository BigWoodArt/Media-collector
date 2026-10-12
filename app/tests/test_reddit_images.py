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

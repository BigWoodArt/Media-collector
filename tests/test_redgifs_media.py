"""Redgifs: stills must be saved as real images, videos stay videos, 'Prioritize' favours videos."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.parse

from tests._net import fetch, reply, err
from sources import SOURCE_BY_ID
from core.thumbs import is_static_video, extract_still, FFMPEG_AVAILABLE

import importlib.util
FFMPEG = bool(FFMPEG_AVAILABLE and shutil.which("ffmpeg") and importlib.util.find_spec("PIL"))


def gif(n, kind="video", type_=1, **over):
    hd = {"video": f"https://media.redgifs.com/v{n}.mp4", "jpg": f"https://media.redgifs.com/i{n}.jpg",
          "poster-only": f"https://media.redgifs.com/p{n}.mp4"}[kind]
    g = {"id": f"g{n}", "title": f"t{n}", "tags": [], "type": type_, "duration": 10.0, "hasAudio": False,
         "urls": {"hd": hd, "sd": hd, "poster": f"https://media.redgifs.com/p{n}-poster.jpg"}}
    g.update(over)
    return g


def site(gifs, blobs=None):
    blobs = blobs or {}
    def h(u):
        if "auth" in u:
            return reply(json.dumps({"token": "T"}))
        if "gifs/search" in u:
            return reply(json.dumps({"gifs": gifs}))
        return reply(blobs.get(u, b"BYTES:" + u.encode()))
    return h


def make_videos(folder):
    """A photo turned into a 10s loop (what a Redgifs 'still' looks like) and a genuinely moving clip."""
    from PIL import Image, ImageDraw
    import random
    random.seed(3)
    im = Image.new("RGB", (320, 240), (30, 60, 120))
    d = ImageDraw.Draw(im)
    for _ in range(200):
        x, y = random.randint(0, 290), random.randint(0, 210)
        d.ellipse([x, y, x + random.randint(5, 30), y + random.randint(5, 30)], outline=(random.randint(0, 255),) * 3)
    photo = os.path.join(folder, "photo.jpg")
    im.save(photo, quality=90)
    still, moving = os.path.join(folder, "still.mp4"), os.path.join(folder, "moving.mp4")
    base = ["ffmpeg", "-loglevel", "error", "-nostdin", "-y"]
    subprocess.run(base + ["-loop", "1", "-i", photo, "-t", "4", "-r", "25", "-pix_fmt", "yuv420p", still], check=True)
    subprocess.run(base + ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25", "-t", "4", "-pix_fmt", "yuv420p", moving], check=True)
    return still, moving


class Defaults(unittest.TestCase):
    def test_redgifs_favours_videos_by_default(self):
        c = SOURCE_BY_ID["redgifs"]
        self.assertTrue(c.has_media_priority)
        self.assertEqual(c.priority_media, "video")
        self.assertTrue(c.default_prioritize)
        for other in ("reddit", "erome", "gelbooru"):
            self.assertEqual(SOURCE_BY_ID[other].priority_media, "image")


class ImagePosts(unittest.TestCase):
    def test_image_url_is_saved_as_a_real_image(self):
        items, *_ = fetch("redgifs", "x", site([gif(1, "jpg", type_=2)]))
        self.assertEqual([(i.media_type, os.path.splitext(i.file_path)[1]) for i in items], [("image", ".jpg")])
        self.assertEqual(items[0].extra["api_type"], 2)

    def test_image_post_with_video_hd_uses_the_poster_picture(self):
        items, urls, *_ = fetch("redgifs", "x", site([gif(1, "poster-only", type_=2)]))
        self.assertEqual(items[0].media_type, "image")
        self.assertTrue(any(u.endswith("p1-poster.jpg") for u in urls))
        self.assertFalse(any(u.endswith("p1.mp4") for u in urls), "the 10-second video must not be downloaded")

    def test_ordinary_video_stays_a_video(self):
        items, *_ = fetch("redgifs", "x", site([gif(1)]))
        self.assertEqual([(i.media_type, os.path.splitext(i.file_path)[1]) for i in items], [("video", ".mp4")])

    def test_first_result_fields_are_logged_for_bug_reports(self):
        items, urls, log, http, got = fetch("redgifs", "x", site([gif(1)]))
        self.assertTrue(any("API sample: type=1 duration=10.0" in m for _, m in log))
        self.assertEqual(items[0].extra["url_keys"], ["hd", "poster", "sd"])


class PrioritizeVideos(unittest.TestCase):
    SEQUENCE = [gif(1, "jpg", 2), gif(2), gif(3, "jpg", 2), gif(4), gif(5), gif(6), gif(7)]

    def test_off_keeps_everything_in_order(self):
        items, *_ = fetch("redgifs", "x", site(self.SEQUENCE), prioritize_images=False)
        self.assertEqual([i.media_type for i in items], ["image", "video", "image", "video", "video", "video", "video"])

    def test_on_keeps_stills_rare(self):
        items, *_ = fetch("redgifs", "x", site(self.SEQUENCE), prioritize_images=True)
        kinds = [i.media_type for i in items]
        self.assertEqual(kinds[0], "video")
        self.assertLessEqual(kinds.count("image") * 4, kinds.count("video"))


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class StillLoopsBecomeJpegs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.still, cls.moving = make_videos(cls.dir)
        with open(cls.still, "rb") as f1, open(cls.moving, "rb") as f2:
            cls.still_bytes, cls.moving_bytes = f1.read(), f2.read()

    def test_detector_tells_them_apart(self):
        self.assertTrue(is_static_video(self.still))
        self.assertFalse(is_static_video(self.moving))

    def test_extract_still_makes_a_full_size_jpeg(self):
        out = os.path.join(self.dir, "frame.jpg")
        self.assertTrue(extract_still(self.still, out))
        from PIL import Image
        with Image.open(out) as im:
            self.assertEqual(im.size, (320, 240))

    def test_still_loop_is_saved_as_jpeg_and_the_mp4_is_removed(self):
        blobs = {"https://media.redgifs.com/v1.mp4": self.still_bytes}
        items, *_ = fetch("redgifs", "x", site([gif(1)], blobs))
        self.assertEqual([i.media_type for i in items], ["image"])
        self.assertTrue(items[0].file_path.endswith(".jpg"))
        self.assertTrue(items[0].extra.get("still_detected"))
        self.assertEqual([f for f in os.listdir(os.path.dirname(items[0].file_path)) if f.endswith(".mp4")], [])

    def test_moving_video_is_left_alone(self):
        blobs = {"https://media.redgifs.com/v1.mp4": self.moving_bytes}
        items, *_ = fetch("redgifs", "x", site([gif(1)], blobs))
        self.assertEqual([(i.media_type, os.path.splitext(i.file_path)[1]) for i in items], [("video", ".mp4")])

    def test_a_video_with_sound_is_never_converted(self):
        blobs = {"https://media.redgifs.com/v1.mp4": self.still_bytes}
        items, *_ = fetch("redgifs", "x", site([gif(1, hasAudio=True)], blobs))
        self.assertEqual(items[0].media_type, "video")

    def test_prioritize_videos_drops_detected_stills(self):
        blobs = {"https://media.redgifs.com/v1.mp4": self.still_bytes, "https://media.redgifs.com/v2.mp4": self.moving_bytes}
        items, *_ = fetch("redgifs", "x", site([gif(1), gif(2)], blobs), prioritize_images=True)
        self.assertEqual([i.media_type for i in items], ["video"])




def api(gifs_for, suggest=None):
    """Fake Redgifs API. gifs_for(params) -> gifs for a search request; suggest(query) -> list | raises."""
    def h(u):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(u).query))
        if "auth/temporary" in u:
            return reply(json.dumps({"token": "T"}))
        if "search/suggest" in u:
            out = suggest(q["query"]) if callable(suggest) else (suggest or [])
            return reply(json.dumps(out))
        if "gifs/search" in u:
            return reply(json.dumps({"gifs": gifs_for(q)}))
        return reply(b"V:" + u.encode())
    return h


def tagged(n, *tags):
    return gif(n, tags=list(tags))


def search_urls(urls):
    return [u for u in urls if "gifs/search" in u]


class TagSearch(unittest.TestCase):
    """Redgifs filters by official tag names (tags=Hypno). search_text= is silently ignored."""

    ON = [tagged(1, "Hypno", "Spiral"), tagged(2, "Hypno"), tagged(3, "hypno", "Femdom")]

    def test_searches_by_the_official_tag_not_free_text(self):
        h = api(lambda q: self.ON if q.get("tags") == "Hypno" else [],
                suggest=[{"text": "Hypno", "gifs": 900}, {"text": "Hypnosis", "gifs": 100}])
        items, urls, log, http, got = fetch("redgifs", "hypno", h)
        self.assertEqual(len(items), 3)
        first = search_urls(urls)[0]
        for part in ("tags=Hypno", "type=g", "order=score"):
            self.assertIn(part, first)
        self.assertNotIn("search_text", first)
        self.assertTrue(any("tag 'hypno' -> 'Hypno'" in m and "Hypnosis (100)" in m for _, m in log))

    def test_exact_suggestion_beats_the_first_suggestion(self):
        h = api(lambda q: self.ON, suggest=[{"text": "Hypnosis", "gifs": 5}, {"text": "Hypno", "gifs": 3}])
        items, urls, *_ = fetch("redgifs", "hypno", h)
        self.assertIn("tags=Hypno&", search_urls(urls)[0] + "&")

    def test_unknown_word_falls_back_to_title_case(self):
        for suggest in ([], urllib.error.HTTPError("u", 404, "x", {}, None)):
            h = api(lambda q: [tagged(1, "Slow Motion")], suggest=(lambda _: (_ for _ in ()).throw(suggest)) if isinstance(suggest, Exception) else suggest)
            items, urls, *_ = fetch("redgifs", "slow motion", h)
            self.assertIn("tags=Slow+Motion", search_urls(urls)[0])
            self.assertEqual(len(items), 1)

    def test_older_parameter_rescues_a_search_when_tags_is_ignored(self):
        h = api(lambda q: [tagged(i, "Other") for i in (7, 8)] if "tags" in q else self.ON)
        items, urls, log, http, got = fetch("redgifs", "hypno", h)
        self.assertEqual(len(items), 3)
        self.assertTrue(any("search_text=" in u for u in search_urls(urls)))
        self.assertTrue(any("tags= filter wasn't applied" in m for _, m in log))

    def test_when_nothing_matches_it_stops_instead_of_downloading_unrelated_videos(self):
        h = api(lambda q: [tagged(i, "Other") for i in (7, 8, 9)])
        items, urls, log, http, got = fetch("redgifs", "hypno", h)
        self.assertEqual(items, [])
        self.assertFalse([u for u in urls if u.endswith(".mp4")], "no unrelated video may be downloaded")
        self.assertTrue(any(l == "error" and "don't match 'hypno'" in m for l, m in log))

    def test_off_topic_results_mixed_in_are_skipped(self):
        mixed = [tagged(1, "Hypno"), tagged(2, "Other"), tagged(3, "Hypno"), tagged(4, "Other"), tagged(5, "Hypno")]
        items, *_ = fetch("redgifs", "hypno", api(lambda q: mixed))
        self.assertEqual(sorted(i.post_id for i in items), ["rg_g1", "rg_g3", "rg_g5"])

    def test_results_that_list_no_tags_are_accepted(self):
        bare = [gif(1, tags=[]), gif(2, tags=[])]
        items, *_ = fetch("redgifs", "hypno", api(lambda q: bare))
        self.assertEqual(len(items), 2)

    def test_several_tags_then_just_the_first_when_together_they_match_nothing(self):
        def gifs_for(q):
            return [] if "," in q.get("tags", "") else self.ON
        items, urls, log, http, got = fetch("redgifs", "hypno, femdom", api(gifs_for, suggest=lambda s: [{"text": s.title(), "gifs": 1}]))
        self.assertEqual(len(items), 3)
        self.assertIn("tags=Hypno%2CFemdom", search_urls(urls)[0])
        self.assertTrue(any("trying just 'Hypno'" in m for _, m in log))

    def test_default_sort_matches_the_websites_score_order(self):
        items, urls, *_ = fetch("redgifs", "hypno", api(lambda q: self.ON))
        self.assertIn("order=score", search_urls(urls)[0])


if __name__ == "__main__":
    unittest.main()

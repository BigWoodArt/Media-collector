"""Redgifs niches: picked by relevance, fetched with the niche API's own orders, tag and text fallbacks."""
import json
import unittest
import urllib.parse

from tests._net import fetch, reply
from sources import SOURCE_BY_ID
from sources.redgifs_source import RedgifsSource, rank_niches


def gif(n, tags=("a",), desc=""):
    return {"id": f"g{n}", "tags": list(tags), "description": desc, "type": 1, "hasAudio": True,
            "duration": 5.0, "urls": {"hd": f"https://media.redgifs.com/v{n}.mp4"}}


def niche(i, name, gifs, tags=()):
    return {"id": i, "name": name, "gifs": gifs, "tags": list(tags)}


# what the live API returned for "hypnotic": loose matches included
HYPNOTIC = [niche("feminization-sissy-captions", "Feminization/Sissy Captions", 14786, ["sissycaption"]),
            niche("hypno-play", "Hypno Play", 1766, ["Hypno", "Hypnosis"]),
            niche("mesmerism-mind-control", "Mesmerism & Mind Control", 713, ["Hypno", "Mind Control"]),
            niche("titty-flexing", "Titty Flexing", 5300, ["Abs", "Tits"]),
            niche("seductive", "Seductive", 4192, ["Sexy", "Tease"]),
            niche("tiny-hypno", "Tiny Hypno", 3, ["Hypno"])]


def site(niches=(), niche_gifs=None, tag_gifs=(), text_gifs=(), suggest=()):
    def h(u):
        path = urllib.parse.urlparse(u).path
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(u).query))
        if path.endswith("/auth/temporary"):
            return reply(json.dumps({"token": "t"}))
        if path == "/v2/search/suggest":
            return reply(json.dumps(list(suggest)))
        if path == "/v2/niches":
            return reply(json.dumps({"niches": list(niches)}))
        if path.startswith("/v2/niches/") and path.endswith("/gifs"):
            if q.get("order") not in ("best", "hot", "latest", "oldest", None):
                return reply(json.dumps({"error": {"code": "BadOrder"}}), 400)
            return reply(json.dumps({"gifs": (niche_gifs or {}).get(path.split("/")[3], [])}))
        if path == "/v2/gifs/search":
            return reply(json.dumps({"gifs": list(tag_gifs if "tags" in q else text_gifs)}))
        return reply(b"CLIP" + u.encode())
    return h


class Ranking(unittest.TestCase):
    def test_only_niches_about_the_word_and_big_enough(self):
        got = [n["id"] for n in rank_niches("hypnotic", HYPNOTIC)]
        self.assertEqual(got, ["hypno-play", "mesmerism-mind-control"])     # name match first; loose ones dropped

    def test_nothing_about_the_word(self):
        self.assertEqual(rank_niches("spiral", [niche("male-squirting-in-chastity", "x", 95, ["Squirt"])]), [])


class Fetching(unittest.TestCase):
    def test_plain_word_uses_relevant_niches_only(self):
        h = site(HYPNOTIC, {"hypno-play": [gif(1), gif(2)], "mesmerism-mind-control": [gif(3)]})
        items, urls, *_ = fetch("redgifs", "hypnotic", h, limit=10)
        self.assertEqual(sorted(i.post_id for i in items), ["rg_g1", "rg_g2", "rg_g3"])
        self.assertTrue(any("/v2/niches/hypno-play/gifs" in u for u in urls))
        self.assertFalse(any("titty-flexing" in u or "seductive" in u for u in urls))

    def test_clip_in_two_niches_is_taken_once(self):
        h = site(HYPNOTIC, {"hypno-play": [gif(1), gif(2)], "mesmerism-mind-control": [gif(2), gif(3)]})
        items, *_ = fetch("redgifs", "hypnotic", h, limit=10)
        self.assertEqual(sorted(i.post_id for i in items), ["rg_g1", "rg_g2", "rg_g3"])

    def test_niche_order_names_the_api_accepts(self):
        h = site(HYPNOTIC, {"hypno-play": [gif(1)]})
        for sort in ("Trending", "Score", "Latest", "Top 7 days", "Top 28 days", "Top"):
            items, urls, log, *_ = fetch("redgifs", "niche:hypno-play", h, sort=sort)
            self.assertEqual(len(items), 1, (sort, log))

    def test_niche_token_skips_the_lookup(self):
        items, urls, *_ = fetch("redgifs", "niche:hypno-play", site(HYPNOTIC, {"hypno-play": [gif(1)]}))
        self.assertEqual([i.post_id for i in items], ["rg_g1"])
        self.assertFalse(any(urllib.parse.urlparse(u).path == "/v2/niches" for u in urls))

    def test_falls_back_to_the_tag(self):
        items, urls, *_ = fetch("redgifs", "spiral", site([], tag_gifs=[gif(1, ("Spiral",))]))
        self.assertEqual(len(items), 1)
        self.assertTrue(any("tags=" in u for u in urls))

    def test_falls_back_to_text_and_keeps_real_mentions(self):
        texts = [gif(1, ("x",), "a hypnotic spiral clip"), gif(2, ("y",), "spiralling into madness"),
                 gif(3, ("z",), "Spirals everywhere")]
        items, *_ = fetch("redgifs", "spiral", site([], tag_gifs=[], text_gifs=texts))
        self.assertEqual(sorted(i.post_id for i in items), ["rg_g1", "rg_g3"])

    def test_tag_token_skips_niches(self):
        items, urls, *_ = fetch("redgifs", "tag:Spiral", site(HYPNOTIC, tag_gifs=[gif(1, ("Spiral",))]))
        self.assertEqual(len(items), 1)
        self.assertFalse(any(urllib.parse.urlparse(u).path == "/v2/niches" for u in urls))


class Suggest(unittest.TestCase):
    def test_niches_then_tags_then_common_tags(self):
        texts = [gif(i, ("Hypno", "Spiral"), "hypno spiral") for i in range(3)] + [gif(9, ("Zed",), "spiral")]
        h = site(HYPNOTIC, text_gifs=texts, suggest=[{"text": "Hypnosis", "gifs": 800}])
        from tests._net import mock, netlog
        import urllib.request
        with mock.patch.object(netlog, "_orig_urlopen", lambda req, timeout=15: h(req.full_url)), \
                mock.patch("time.sleep"):
            urllib.request.urlopen = netlog._wrapped
            out = RedgifsSource.suggest("spiral")
            hyp = RedgifsSource.suggest("hypnotic")
        self.assertEqual([o["value"] for o in hyp[:2]], ["niche:hypno-play", "niche:mesmerism-mind-control"])
        self.assertEqual(hyp[0]["count"], 1766)
        values = [o["value"] for o in out]
        self.assertIn("tag:Hypnosis", values)
        self.assertIn("tag:Hypno", values)
        self.assertNotIn("tag:Zed", values)       # used once only
        self.assertEqual(SOURCE_BY_ID["redgifs"], RedgifsSource)


if __name__ == "__main__":
    unittest.main()

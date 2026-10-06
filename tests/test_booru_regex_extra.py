"""Extra parser checks: decoys from saved page fixtures + real file URLs seen in a live run."""
import unittest

from sources.booru_family import FILE_URL_RES


def original(text):
    for rx in FILE_URL_RES:
        m = rx.search(text)
        if m:
            return m.group(0)
    return None


class FileUrlShapes(unittest.TestCase):
    def test_real_urls_from_a_live_run(self):
        for site, url in (("rule34", "https://wimg.rule34.xxx//images/3903/791aaed23b3053f2e87e05336acf077a.jpeg"),
                          ("realbooru", "https://realbooru.com//images/cd/24/cd24a4858401901173f4d4f45d93b0c0.jpeg"),
                          ("gelbooru", "https://img4.gelbooru.com//images/26/aa/26aaad9b7033b6b6da3823602c7e8e58.png"),
                          ("safebooru", "https://safebooru.org/images/4433/0dc79b85d1879ec35a5da60e638f0d4d6d9f600d.png")):
            with self.subTest(site=site):
                self.assertEqual(original(f'<a href="{url}">Original</a>'), url)

    def test_wrapper_link_is_never_returned_whole(self):
        page = ('<a href="http://waifu2x.booru.pics/Home/fromlink?denoise=1&scale=2&url='
                'https://hypnohub.net//images/1c/a6/1ca6459f282cc386efc1675e3f52d96c.gif">Waifu2x</a>')
        self.assertEqual(original(page), "https://hypnohub.net//images/1c/a6/1ca6459f282cc386efc1675e3f52d96c.gif")

    def test_samples_and_thumbnails_never_match(self):
        page = ('<img src="https://img4.gelbooru.com/samples/ab/cd/sample_abcdef0123456789abcdef0123456789.jpg">'
                '<img src="https://img4.gelbooru.com/thumbnails/ab/cd/thumbnail_abcdef0123456789abcdef0123456789.jpg">')
        self.assertIsNone(original(page))


if __name__ == "__main__":
    unittest.main()

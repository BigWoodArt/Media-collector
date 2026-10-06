"""Website-fallback parser tests on synthetic pages."""
import unittest

from sources.booru_family import FILE_URL_RES, LIST_ID_RES
from tests._pages import list_page, post_page


def list_ids(page):
    ids = []
    for rx in LIST_ID_RES:
        for found in rx.findall(page):
            if found not in ids:
                ids.append(found)
    return ids


def original_url(page):
    for rx in FILE_URL_RES:
        m = rx.search(page)
        if m:
            return m.group(0)
    return None


class ListPages(unittest.TestCase):
    def test_every_post_is_found_once_whatever_the_page_size(self):
        for count in (42, 40, 3):            # boards differ: 42 per page, RealBooru 40
            with self.subTest(count=count):
                ids = list_ids(list_page(14886885, count))
                self.assertEqual(len(ids), count)
                self.assertEqual(ids[0], "14886885")

    def test_pager_and_tag_links_are_not_mistaken_for_posts(self):
        self.assertEqual(list_ids(list_page(100, 0)), [])


class PostPages(unittest.TestCase):
    def test_original_file_found_and_decoys_ignored(self):
        for style in ("gelbooru", "hypnohub", "realbooru"):
            with self.subTest(style=style):
                page, name = post_page(style)
                url = original_url(page)
                self.assertIsNotNone(url)
                self.assertTrue(url.endswith(name), url)
                for decoy in ("/samples/", "/thumbnails", "upscale", "reverse"):
                    self.assertNotIn(decoy, url)


if __name__ == "__main__":
    unittest.main()

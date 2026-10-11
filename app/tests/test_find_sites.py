import unittest
from core.collector import has_lookup
from sources import SOURCE_CLASSES, SOURCE_BY_ID


class FindSites(unittest.TestCase):
    def test_lookup_sites_are_found(self):
        have = {c.id for c in SOURCE_CLASSES if has_lookup(c)}
        self.assertIn("reddit", have)
        self.assertIn("redgifs", have)

    def test_find_asks_only_the_ids_given(self):
        from unittest import mock
        from core import collector
        asked = []
        with mock.patch.object(SOURCE_BY_ID["reddit"], "suggest", classmethod(lambda cls, q: asked.append("reddit") or [])), \
                mock.patch.object(SOURCE_BY_ID["redgifs"], "suggest", classmethod(lambda cls, q: asked.append("redgifs") or [])):
            collector.suggest_all("x", ["redgifs"])
        self.assertEqual(asked, ["redgifs"])


if __name__ == "__main__":
    unittest.main()

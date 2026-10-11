import unittest
from core import updates


class Updates(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updates.parse_version('x\nAPP_VERSION = "0.1.12"\n'), (0, 1, 12))
        self.assertIsNone(updates.parse_version("<html>404</html>"))
        self.assertIsNone(updates.parse_version(None))

    def test_newer(self):
        self.assertEqual(updates.newer_available("0.1.11", lambda: (0, 1, 12)), "0.1.12")
        self.assertEqual(updates.newer_available("0.1.9", lambda: (0, 1, 10)), "0.1.10")   # not a string compare
        self.assertIsNone(updates.newer_available("0.1.11", lambda: (0, 1, 11)))
        self.assertIsNone(updates.newer_available("0.2.0", lambda: (0, 1, 11)))
        self.assertIsNone(updates.newer_available("0.1.11", lambda: None))

    def test_never_raises_offline(self):
        from unittest import mock
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertIsNone(updates.latest_version())

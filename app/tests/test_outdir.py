import json, os, tempfile, unittest
from core import settings

class OutDir(unittest.TestCase):
    def test_stale_collections_path_resets(self):
        old = settings.SETTINGS_FILE
        d = tempfile.mkdtemp()
        f = os.path.join(d, "s.json")
        json.dump({"output_dir": os.path.join(d, "other_app", "collections")}, open(f, "w"))
        settings.SETTINGS_FILE = f
        try:
            self.assertEqual(settings.load()["output_dir"], settings.DEFAULTS["output_dir"])
            json.dump({"output_dir": os.path.join(d, "mine")}, open(f, "w"))
            self.assertEqual(settings.load()["output_dir"], os.path.join(d, "mine"))
        finally:
            settings.SETTINGS_FILE = old

"""Child programs must never open a console window on Windows (an empty frame that steals clicks)."""
import ast
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from core.winproc import quiet

ROOT = Path(__file__).resolve().parent.parent
SHARED = sorted((ROOT / "sources").glob("*.py")) + [ROOT / "core" / n for n in
          ("thumbs.py", "netlog.py", "query_clean.py", "media_item.py", "winproc.py")]


class Quiet(unittest.TestCase):
    def test_adds_nothing_off_windows(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertEqual(quiet(), {})

    def test_hides_the_window_on_windows(self):
        info = types.SimpleNamespace(dwFlags=0, wShowWindow=1)
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.object(subprocess, "STARTUPINFO", lambda: info, create=True), \
                mock.patch.object(subprocess, "STARTF_USESHOWWINDOW", 1, create=True), \
                mock.patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
            kw = quiet()
        self.assertEqual(kw["creationflags"], 0x08000000)
        self.assertEqual((kw["startupinfo"].dwFlags & 1, kw["startupinfo"].wShowWindow), (1, 0))


class EverySharedSubprocessCallIsQuiet(unittest.TestCase):
    def test_no_bare_subprocess_calls_in_shared_files(self):
        bad = []
        for path in SHARED:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"
                        and node.func.attr in ("run", "Popen", "call", "check_call", "check_output")):
                    has_quiet = any(k.arg is None and isinstance(k.value, ast.Call)
                                    and getattr(k.value.func, "id", "") == "quiet" for k in node.keywords)
                    if not has_quiet:
                        bad.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(bad, [], "subprocess call without **quiet() would flash a window on Windows")


if __name__ == "__main__":
    unittest.main()

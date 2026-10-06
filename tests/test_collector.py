"""Offline tests for the headless collector: python -m unittest tests.test_collector"""
import json
import os
import queue
import tempfile
import unittest
import zipfile
from unittest import mock

from core.collector import Collection, Job, Options, Pick, suggest_all
from core.media_item import MediaItem
from sources import SOURCE_BY_ID
from sources.base import Source


class FakeSource(Source):
    id, label, category = "fake", "Fake", "Test"
    supports_quality = True
    calls = []

    @classmethod
    def resolve_quality(cls, q):
        return {"query_suffix": "score:>=9"} if q == "Best" else {}

    @classmethod
    def suggest(cls, query):
        return [{"value": query + "_a", "label": "Fake " + query, "count": 7}]

    def fetch(self, query, limit, sort, time_range, dest_dir, log, progress, stop_event,
              early_preview_cb=None, randomize=False, prioritize_images=False, item_cb=None, skip_ids=None):
        FakeSource.calls.append(query)
        out = []
        for i, mt in enumerate(("image", "video", "image")):
            pid = f"f_{i}"
            if skip_ids and pid in skip_ids:
                continue
            path = os.path.join(dest_dir, f"{i}.bin")
            with open(path, "wb") as f:
                f.write(b"\x89PNG" + bytes([i]))
            it = MediaItem(file_path=path, caption="c", media_type=mt, post_id=pid, source_type="fake")
            out.append(it)
            item_cb(it)
        return out


class Boom(FakeSource):
    id, label = "boom", "Boom"

    def fetch(self, *a, **k):
        raise RuntimeError("kaput")


def drain(job):
    ev = []
    job.start()
    job.thread.join(10)
    while True:
        try:
            ev.append(job.events.get_nowait())
        except queue.Empty:
            return ev


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        FakeSource.calls = []
        self.patch = mock.patch.dict(SOURCE_BY_ID, {"fake": FakeSource, "boom": Boom})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def run_job(self, picks, **opt):
        col = Collection(self.tmp, "Cats")
        job = Job(col, picks, Options(**opt))
        return col, drain(job)

    def test_collects_and_filters_types(self):
        col, ev = self.run_job([Pick("fake", "cat")], types={"image"})
        kept = [e for e in ev if e[0] == "item"]
        self.assertEqual(len(kept), 2)
        done = [e for e in ev if e[0] == "pick_done"][0]
        self.assertEqual(done[2:4], (2, "done"))
        self.assertIn("f_1", col.seen)                       # excluded video still remembered

    def test_second_run_adds_nothing_new(self):
        self.run_job([Pick("fake", "cat")])
        col, ev = self.run_job([Pick("fake", "cat")])
        self.assertEqual([e for e in ev if e[0] == "item"], [])
        self.assertEqual([e for e in ev if e[0] == "pick_done"][0][3], "empty")

    def test_quality_suffix_applied(self):
        self.run_job([Pick("fake", "cat")], quality="Best")
        self.assertEqual(FakeSource.calls, ["cat score:>=9"])

    def test_one_broken_site_does_not_stop_the_rest(self):
        col, ev = self.run_job([Pick("boom", "x"), Pick("fake", "cat")])
        states = [e[3] for e in ev if e[0] == "pick_done"]
        self.assertEqual(states, ["failed", "done"])
        self.assertEqual(ev[-1][0], "done")

    def test_reject_deletes_and_remembers(self):
        col, ev = self.run_job([Pick("fake", "cat")])
        item = [e for e in ev if e[0] == "item"][0][2]
        col.reject(item.post_id, item.file_path)
        col.save()
        self.assertFalse(os.path.exists(item.file_path))
        again = Collection(self.tmp, "Cats")
        self.assertIn(item.post_id, again.rejected)
        self.assertIn(item.post_id, again.skip_ids())

    def test_stop_before_start_runs_nothing(self):
        col = Collection(self.tmp, "Cats")
        job = Job(col, [Pick("fake", "cat")], Options())
        job.stop()
        ev = drain(job)
        self.assertEqual([e[0] for e in ev], ["done"])

    def test_export_zip_excludes_bookkeeping(self):
        col, ev = self.run_job([Pick("fake", "cat")])
        z = os.path.join(self.tmp, "out.zip")
        n = col.export_zip(z)
        self.assertEqual(n, 3)
        self.assertFalse(any(x.endswith("collection.json") for x in zipfile.ZipFile(z).namelist()))

    def test_error_page_downloads_are_discarded(self):
        class Bad(FakeSource):
            id, label = "bad", "Bad"
            def fetch(s, query, limit, sort, tr, dest, log, prog, stop, *a, item_cb=None, skip_ids=None, **k):
                p = os.path.join(dest, "x.jpg")
                with open(p, "wb") as f:
                    f.write(b"<html>blocked</html>")
                item_cb(MediaItem(p, "c", "image", post_id="b_1"))
                return []
        with mock.patch.dict(SOURCE_BY_ID, {"bad": Bad}):
            col, ev = self.run_job([Pick("bad", "q")])
        self.assertEqual([e for e in ev if e[0] == "item"], [])

    def test_suggest_all_collects_and_tolerates_failures(self):
        class Dead(FakeSource):
            id, label = "dead", "Dead"
            @classmethod
            def suggest(cls, q):
                raise OSError("down")
        with mock.patch.dict(SOURCE_BY_ID, {"dead": Dead}):
            r = suggest_all("cat", ["fake", "dead"])
        self.assertEqual([x["value"] for x in r], ["cat_a"])


if __name__ == "__main__":
    unittest.main()


class PersistenceAndRanking(unittest.TestCase):
    def test_saved_searches_round_trip_with_quality_and_limit(self):
        tmp = tempfile.mkdtemp()
        c = Collection(tmp, "Cats")
        c.picks = [Pick("fake", "cat", "Fake cat", "Best", 25), Pick("fake", "dog")]
        c.save()
        again = Collection(tmp, "Cats")
        self.assertEqual([(p.value, p.quality, p.limit) for p in again.picks], [("cat", "Best", 25), ("dog", "", 0)])

    def test_per_search_quality_and_limit_win_over_defaults(self):
        tmp = tempfile.mkdtemp()
        FakeSource.calls = []
        with mock.patch.dict(SOURCE_BY_ID, {"fake": FakeSource}):
            job = Job(Collection(tmp, "C"), [Pick("fake", "a", quality="Best"), Pick("fake", "b")],
                      Options(quality="Any", limit=9))
            drain(job)
        self.assertEqual(FakeSource.calls, ["a score:>=9", "b"])

    def test_matches_sorted_by_popularity_across_sites_with_floor(self):
        class A(FakeSource):
            id, label = "a", "A"
            @classmethod
            def suggest(cls, q):
                return [{"value": "small", "count": 12}, {"value": "mid", "count": 5000}, {"value": "nosize"}]
        class B(FakeSource):
            id, label = "b", "B"
            @classmethod
            def suggest(cls, q):
                return [{"value": "big", "count": 900000}, {"value": "mid", "count": 5000}]
        with mock.patch.dict(SOURCE_BY_ID, {"a": A, "b": B}):
            r = suggest_all("x", ["a", "b"], min_count=100)
        self.assertEqual([(m["source"], m["value"]) for m in r],
                         [("b", "big"), ("a", "mid"), ("b", "mid"), ("a", "nosize")])

    def test_verbose_log_has_start_http_and_end_lines_and_no_secrets(self):
        tmp = tempfile.mkdtemp()

        class Keyed(FakeSource):
            def __init__(self, api_key=""):
                self.api_key = api_key
        with mock.patch.dict(SOURCE_BY_ID, {"fake": Keyed}):
            job = Job(Collection(tmp, "C"), [Pick("fake", "a")], Options(), {"fake": {"api_key": "SECRETKEY"}})
            ev = drain(job)
        text = "\n".join(str(e[1]) for e in ev if e[0] == "log")
        self.assertIn("START", text)
        self.assertIn("END status=", text)
        self.assertNotIn("SECRETKEY", text)

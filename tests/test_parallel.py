import os, tempfile, threading, time, unittest
from unittest import mock
from core.collector import Collection, Job, Options, Pick
from core.media_item import MediaItem
from sources import SOURCE_BY_ID
from sources.base import Source
from tests.test_collector import drain

LOG = []
ACTIVE = {"n": 0, "max": 0}
LOCK = threading.Lock()


class Slow(Source):
    id, label, category = "slow", "Slow", "Test"
    order_choices, default_order, min_score_choices = [("a", "A", {})], "a", [("", "Any", {})]
    tag = b"s"

    def fetch(self, query, limit, sort, tr, dest, log, progress, stop, early=None, rnd=False, pri=False,
              item_cb=None, skip_ids=None):
        with LOCK:
            ACTIVE["n"] += 1; ACTIVE["max"] = max(ACTIVE["max"], ACTIVE["n"]); LOG.append(("start", self.id, query))
        for _ in range(10):
            if stop.is_set():
                break
            time.sleep(0.02)
        path = os.path.join(dest, "f.bin")
        open(path, "wb").write(b"\x89PNG" + self.tag + query.encode())
        item_cb(MediaItem(file_path=path, caption="c", media_type="image", post_id=self.id + query, source_type=self.id))
        with LOCK:
            ACTIVE["n"] -= 1; LOG.append(("end", self.id, query))
        return []


class Other(Slow):
    id, label = "other", "Other"


class Third(Slow):
    id, label = "third", "Third"


class Parallel(unittest.TestCase):
    def run_it(self, par, picks):
        LOG.clear(); ACTIVE.update(n=0, max=0)
        tmp = tempfile.mkdtemp()
        with mock.patch.dict(SOURCE_BY_ID, {"slow": Slow, "other": Other, "third": Third}):
            ev = drain(Job(Collection(tmp, "C"), picks, Options(parallel=par)))
        return tmp, ev

    def test_sites_overlap(self):
        tmp, ev = self.run_it(3, [Pick("slow", "a"), Pick("other", "b"), Pick("third", "c")])
        self.assertEqual(ACTIVE["max"], 3)
        self.assertEqual(sorted(f for f in os.listdir(tmp + "/C") if f.endswith(".bin")), ["other_f.bin", "slow_f.bin", "third_f.bin"])
        self.assertEqual(len([e for e in ev if e[0] == "pick_done" and e[3] == "done"]), 3)

    def test_same_site_stays_in_order(self):
        tmp, ev = self.run_it(3, [Pick("slow", "a"), Pick("slow", "b")])
        self.assertEqual(ACTIVE["max"], 1)

    def test_one_at_a_time(self):
        tmp, ev = self.run_it(1, [Pick("slow", "a"), Pick("other", "b")])
        self.assertEqual(ACTIVE["max"], 1)

    def test_skip_source_hits_running_only(self):
        LOG.clear()
        tmp = tempfile.mkdtemp()
        with mock.patch.dict(SOURCE_BY_ID, {"slow": Slow, "other": Other}):
            job = Job(Collection(tmp, "C"), [Pick("slow", "a"), Pick("other", "b")], Options(parallel=2))
            job.start(); time.sleep(0.05); job.skip_source(); job.thread.join(10)
        self.assertFalse(job.thread.is_alive())


if __name__ == "__main__":
    unittest.main()

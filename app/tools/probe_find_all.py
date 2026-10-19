"""Live check of every site's Find lookup: python tools/probe_find_all.py [word ...]
Writes find_all_probe.txt next to the program."""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import collector, settings   # noqa: E402,F401
from sources import SOURCE_CLASSES   # noqa: E402

words = sys.argv[1:] or ["blonde", "spiral"]


def one(job):
    cls, w = job
    t0 = time.time()
    try:
        res, err = cls.suggest(w), ""
    except Exception as ex:
        res, err = [], f"  RAISED {ex!r}"
    head = f"\n== {cls.id} / {w}: {len(res)} result(s) in {time.time() - t0:.1f}s{err}"
    return head + "".join(f"\n   {str(r['value'])[:48]:48} {r['label'][:60]}  {r['count']}" for r in res[:6])


lines = [f"Find probe (all sites) {time.strftime('%Y-%m-%d %H:%M:%S')}"]
with ThreadPoolExecutor(8) as ex:
    lines += list(ex.map(one, [(c, w) for c in SOURCE_CLASSES for w in words]))
open(os.path.join(settings.APP_DIR, "find_all_probe.txt"), "w", encoding="utf-8").write("\n".join(lines))
print("done")

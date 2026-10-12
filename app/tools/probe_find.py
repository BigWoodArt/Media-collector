"""Live check of Find lookups: python tools/probe_find.py pmvhaven hypnotube -- hypnotic spiral
Writes find_probe.txt next to the program."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import collector, settings   # noqa: E402,F401  (importing collector installs the HTTP logging)
from sources import SOURCE_BY_ID   # noqa: E402

args = sys.argv[1:]
sites, words = (args[:args.index("--")], args[args.index("--") + 1:]) if "--" in args else (args, [])
sites = sites or ["pmvhaven", "hypnotube"]
words = words or ["hypnotic", "spiral"]
lines = [f"Find probe {time.strftime('%Y-%m-%d %H:%M:%S')}"]
for site in sites:
    for w in words:
        t0 = time.time()
        try:
            res = SOURCE_BY_ID[site].suggest(w)
            err = ""
        except Exception as ex:
            res, err = [], f"  RAISED {ex!r}"
        lines.append(f"\n== {site} / {w}: {len(res)} result(s) in {time.time() - t0:.1f}s{err}")
        lines += [f"   {r['value']:40} {r['label']}  {r['count']}" for r in res]
open(os.path.join(settings.APP_DIR, "find_probe.txt"), "w", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines))

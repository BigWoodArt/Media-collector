"""Live check of PornPics paging and result sizes. Writes pornpics_probe.txt next to the program."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import collector, settings   # noqa: E402,F401
from sources import SOURCE_BY_ID   # noqa: E402

site = SOURCE_BY_ID["pornpics"]()
B = "https://www.pornpics.com"
lines = [f"PornPics probe {time.strftime('%Y-%m-%d %H:%M:%S')}"]


def links(url):
    try:
        return site._gallery_links(site._get_text(url))
    except Exception as ex:
        return None


def size(base, hi):
    """Smallest offset (multiple of 20) that returns nothing = number of galleries."""
    sep = "&" if "?" in base else "?"
    lo = 0
    while lo + 20 < hi:
        mid = (lo + hi) // 40 * 20
        got = links(f"{B}{base}{sep}limit=20&offset={mid}")
        if got:
            lo = mid
        else:
            hi = mid
    return hi


for base, hi in (("/blonde/", 1000), ("/tags/blonde-shemale/", 1000), ("/tags/blonde-teen/", 1000),
                 ("/?q=blonde", 100000), ("/search/srch.php?q=blonde&lang=en", 100000)):
    sep = "&" if "?" in base else "?"
    a, b, c = (links(f"{B}{base}{sep}limit=20&offset={o}") or [] for o in (0, 20, 5000 if hi > 1000 else 500))
    same = "same as first page" if c and c[:3] == a[:3] else "different content"
    t0 = time.time()
    lines.append(f"{base}: p1={len(a)} p2={len(b)} far={len(c)} ({same}); p2 differs={b[:3] != a[:3]}; "
                 f"size about {size(base, hi)} galleries ({time.time() - t0:.0f}s)")
    open(os.path.join(settings.APP_DIR, "pornpics_probe.txt"), "w", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines))

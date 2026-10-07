"""Audit the Find section: ask every site's lookup for a term and report what each one says.
    python tools/find_audit.py [term ...]      (default terms: cat, cosplay)
Writes find_audit_report.txt next to the program: per term and site the result count, time, and the first matches
(value + size when the site tells). 'no lookup' = the site has no Find support; 0 results = the site answered nothing
(or was unreachable - lookups never raise, so those look the same). Paste the report back for a fix list."""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import collector, settings   # noqa: E402,F401  (importing collector installs the HTTP logging)
from sources import SOURCE_CLASSES      # noqa: E402
from sources.base import Source         # noqa: E402


def lookup(cls, term, out):
    t0 = time.time()
    try:
        found = cls.suggest(term) or []
        out[cls.id] = (found, round(time.time() - t0, 1), "")
    except Exception as ex:             # lookups should never raise: this is a bug worth reporting
        out[cls.id] = ([], round(time.time() - t0, 1), f"RAISED {type(ex).__name__}: {ex}")


def main(terms):
    lines = []
    for term in terms:
        out = {}
        threads = []
        for cls in SOURCE_CLASSES:
            if cls.suggest.__func__ is Source.suggest.__func__:
                out[cls.id] = None
                continue
            th = threading.Thread(target=lookup, args=(cls, term, out), daemon=True)
            th.start()
            threads.append(th)
        for th in threads:
            th.join(40)
        lines.append(f"=== term: {term!r}")
        for cls in SOURCE_CLASSES:
            r = out.get(cls.id, ([], 40.0, "no answer in 40 s"))
            if r is None:
                lines.append(f"  {cls.label:<16} no lookup")
                continue
            found, secs, err = r
            lines.append(f"  {cls.label:<16} {len(found):>3} result(s) in {secs}s {err}")
            for m in found[:3]:
                n = m.get("count")
                lines.append(f"      - {m.get('label') or m.get('value')}  [{m.get('value')}]  "
                             f"{'' if n is None else str(n) + ' items'}")
        print("\n".join(lines[-len(SOURCE_CLASSES) - 1:]))
    path = os.path.join(settings.APP_DIR, "find_audit_report.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nReport written: {path}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["cat", "cosplay"])

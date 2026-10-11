"""Live check of the Redgifs lookups: python tools/probe_redgifs.py hypnotic spiral
Writes redgifs_probe.txt next to the program."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import collector, settings   # noqa: E402,F401  (importing collector installs the HTTP logging)
from sources.redgifs_source import RedgifsSource   # noqa: E402

words = sys.argv[1:] or ["hypnotic", "spiral"]
lines = [f"Redgifs probe {time.strftime('%Y-%m-%d %H:%M:%S')}"]
for w in words:
    lines.append(f"\n== {w}")
    for s in RedgifsSource.suggest(w):
        lines.append(f"   {s['value']:45} {s['label']}  {s['count']}")
open(os.path.join(settings.APP_DIR, "redgifs_probe.txt"), "w", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines))

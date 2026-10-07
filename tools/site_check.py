"""Run the site check without the window and write a full report you can paste/upload.
    python tools/site_check.py [site_id ...]      (no ids = every site)
Writes site_check_report.txt next to the program: per site the result, the reason, and every HTTP call with status and
the start of the response body. Uses the credentials saved in Settings."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import collector, netlog, settings   # noqa: E402
import sources                                  # noqa: E402


def main(ids):
    netlog.install()
    if ids:
        keep = [c for c in sources.SOURCE_CLASSES if c.id in ids]
        sources.SOURCE_CLASSES[:] = keep
        collector.SOURCE_CLASSES[:] = keep
    creds = settings.credentials_for(settings.load())
    t0 = time.time()
    res, tmp = collector.check_sites(creds, on_result=lambda r: print(f"{r['label']:<28}{r['result']:<8}{r['detail'][:90]}"))
    lines = []
    for r in res:
        lines.append(f"=== {r['label']} [{r['id']}]  {r['result'].upper()}  {r['elapsed']}s  query={r['query']!r}")
        if r["detail"]:
            lines.append(f"  detail: {r['detail']}")
        for m in r.get("messages", []):
            lines.append(f"  log: {m[:300]}")
        for h in r["http"]:
            lines.append(f"  HTTP {h.get('status')} {h.get('ms')}ms {h.get('url')}"
                         + (f"  ERROR {h['error']}" if h.get("error") else ""))
            if h.get("body") and (h.get("error") or (h.get("status") or 0) >= 400):
                lines.append(f"     body: {h['body'][:300]!r}")
    path = os.path.join(settings.APP_DIR, "site_check_report.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{len(res)} sites, {time.time() - t0:.0f}s\n" + "\n".join(lines) + "\n")
    print(f"\nReport written: {path}")


if __name__ == "__main__":
    main(set(sys.argv[1:]))

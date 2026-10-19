"""Try several addresses on a gallery site and report what each returns: exec this file (optionally set SITE first).
Writes page_dump.txt (summary) and page_dump_N.txt (the pages)."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import settings   # noqa: E402
from sources import SOURCE_BY_ID   # noqa: E402

SITE = globals().get("SITE", "babehub")
URLS = globals().get("URLS") or [
    "https://www.babehub.com/?s=blonde", "https://www.babehub.com/search/blonde/",
    "https://www.babehub.com/search/?q=blonde", "https://www.babehub.com/search/?s=blonde",
    "https://www.babehub.com/tag/blonde/", "https://www.babehub.com/tags/", "https://www.babehub.com/search/"]
site = SOURCE_BY_ID[SITE]()
out = []
for n, url in enumerate(URLS):
    try:
        raw = site._get_text(url)
    except Exception as ex:
        out.append(f"{url}\n   ERROR {ex!r}")
        continue
    title = (re.search(r"<title>(.*?)</title>", raw, re.S) or [0, ""])[1].strip()
    out.append(f"{url}\n   {len(raw)} bytes, title={title[:70]!r}, galleries={len(site._gallery_links(raw))}, file=page_dump_{n}.txt")
    open(os.path.join(settings.APP_DIR, f"page_dump_{n}.txt"), "w", encoding="utf-8").write(raw)
open(os.path.join(settings.APP_DIR, "page_dump.txt"), "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))

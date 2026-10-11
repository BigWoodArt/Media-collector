"""Probe PMV Haven + HypnoTube (read-only GETs). Run: python tools\\probe_video_sites.py  -> probe_video_sites.txt"""
import os, re, sys, json, urllib.request, urllib.error, urllib.parse
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
     "Accept": "text/html,application/json,*/*", "Accept-Language": "en-US,en;q=0.9"}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_video_sites.txt")
lines = []

def _hook(t, v, tb):
    import traceback
    traceback.print_exception(t, v, tb)
    input("Error. Press Enter to close.")
sys.excepthook = _hook

def log(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)

def get(url, n=400000):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=20)
        return r.status, r.headers.get("Content-Type", ""), r.read(n).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, "", e.read(2000).decode("utf-8", "ignore")
    except Exception as e:
        return 0, "", f"ERR {type(e).__name__}: {e}"

def show(url, extra=True):
    st, ct, body = get(url)
    log(f"\n=== {url}\nstatus={st} type={ct} len={len(body)}")
    if st != 200:
        log(body[:300]); return body
    log("title:", (re.search(r"<title>(.*?)</title>", body, re.S) or [0, ""])[1].strip()[:120])
    for pat, name in ((r'https?://[^"\'\s<>\\]+\.(?:mp4|m3u8|webm)[^"\'\s<>\\]*', "media"),
                      (r'(?:href|src|action)="([^"]*(?:search|tag|model|creator|api)[^"]*)"', "links"),
                      (r'<script id="__NEXT_DATA__"[^>]*>(.{0,600})', "next"),
                      (r'<script[^>]+type="application/ld\+json"[^>]*>(.{0,800})', "ldjson"),
                      (r'<(?:source|video)[^>]+>', "videotag")):
        found = list(dict.fromkeys(m if isinstance(m, str) else m[0] for m in re.findall(pat, body, re.S)))[:12]
        if found:
            log(f"[{name}]"); [log("  ", f[:300]) for f in found]
    return body

# ---- HypnoTube
b = show("https://hypnotube.com/")
for u in ("https://hypnotube.com/search/videos/?search_query=spiral", "https://hypnotube.com/search/spiral/",
          "https://hypnotube.com/videos/?search=spiral", "https://hypnotube.com/channels/11/hypnosis/"):
    b = show(u)
m = re.search(r'href="(https://hypnotube\.com/video/[^"]+\.html)"', b) or re.search(r'href="(/video/[^"]+\.html)"', b)
if m:
    show(urllib.parse.urljoin("https://hypnotube.com/", m.group(1)))
# ---- PMV Haven
b = show("https://pmvhaven.com/")
for u in ("https://pmvhaven.com/search?q=spiral", "https://pmvhaven.com/browse?search=spiral",
          "https://pmvhaven.com/api/videos?search=spiral", "https://pmvhaven.com/api/v2/search?q=spiral",
          "https://pmvhaven.com/api/v1/videos/search?q=spiral"):
    show(u)
m = re.search(r'/video/[a-z0-9\-_]+_[0-9a-f]{24}', b or "")
if m:
    show("https://pmvhaven.com" + m.group(0))
open(OUT, "w", encoding="utf-8").write("\n".join(lines))
log("\nwritten", os.path.abspath(OUT))
try:
    input("Done. Press Enter to close.")
except Exception:
    pass

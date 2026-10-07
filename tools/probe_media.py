"""Why can't a media file be fetched?   python tools/probe_media.py URL
Tries the address families and a few header sets against one URL and prints what each does (8 s limit each).
Typical use: Coomer/Kemono answer the API but time out on /data/... files. Paste the output back."""
import socket
import sys
import time
import urllib.request
from urllib.parse import urlparse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
SETS = {
    "app headers (Accept: text/css)": {"User-Agent": "MediaCollector/0.1.8 (public-media-source)", "Accept": "text/css"},
    "browser UA, default Accept": {"User-Agent": UA},
    "browser UA + Referer": {"User-Agent": UA, "Referer": "{origin}/", "Accept": "image/avif,image/webp,*/*"},
}


def main(url):
    u = urlparse(url)
    host, port = u.hostname, u.port or (443 if u.scheme == "https" else 80)
    origin = f"{u.scheme}://{u.netloc}"
    print(f"DNS {host}:")
    for fam, name in ((socket.AF_INET, "IPv4"), (socket.AF_INET6, "IPv6")):
        try:
            addr = socket.getaddrinfo(host, port, fam, socket.SOCK_STREAM)[0][4][0]
        except OSError as ex:
            print(f"  {name}: no address ({ex})")
            continue
        t0 = time.time()
        try:
            socket.create_connection((addr, port), timeout=8).close()
            print(f"  {name} {addr}: connect OK {time.time() - t0:.1f}s")
        except OSError as ex:
            print(f"  {name} {addr}: connect FAILED {time.time() - t0:.1f}s {ex}")
    for name, h in SETS.items():
        h = {k: v.format(origin=origin) for k, v in h.items()}
        h["Range"] = "bytes=0-1023"
        t0 = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=8) as r:
                print(f"{name}: HTTP {r.status} {len(r.read(1024))} bytes, final URL {r.geturl()[:100]} ({time.time() - t0:.1f}s)")
        except Exception as ex:
            print(f"{name}: FAILED {type(ex).__name__}: {ex} ({time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main(sys.argv[1])

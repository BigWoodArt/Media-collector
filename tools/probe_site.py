"""Probe a site before writing a scraper:  python tools/probe_site.py URL [--browser]
Reports HTTP status, content type, whether a browser check/login wall is present, and the image/video URLs found.
--browser re-tries with a real browser engine (pip install playwright; playwright install chromium), the way
you would open the page yourself. Add your own login cookies with --cookies "name=value; name2=value2"."""
import argparse
import re
import sys
import urllib.error
import urllib.request

MEDIA_RE = re.compile(r"""https?://[^\s"'<>()]+?\.(?:jpe?g|png|gif|webp|mp4|webm)(?:\?[^\s"'<>()]*)?""", re.I)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"


def verdict(status, html):
    low = html[:5000].lower()
    if "just a moment" in low or "cf-chl" in low or "attention required" in low:
        return "browser check (Cloudflare-style) - plain HTTP is blocked; try --browser"
    if status in (401, 403):
        return f"HTTP {status} - access refused (login or block)"
    if "age verification" in low or "enter site" in low or "i am 18" in low:
        return "age gate - may need a cookie set once in a normal browser"
    return "page served"


def report(label, status, ctype, html):
    urls = list(dict.fromkeys(MEDIA_RE.findall(html)))
    print(f"[{label}] status={status} type={ctype} size={len(html)}")
    print(f"[{label}] verdict: {verdict(status, html)}")
    print(f"[{label}] media URLs found: {len(urls)}")
    for u in urls[:8]:
        print("   ", u)


def plain(url, cookies):
    headers = {"User-Agent": UA}
    if cookies:
        headers["Cookie"] = cookies
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
            report("http", r.status, r.headers.get("Content-Type", "?"), r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        report("http", e.code, e.headers.get("Content-Type", "?"), e.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"[http] failed: {e}")


def browser(url, cookies):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[browser] Playwright not installed: pip install playwright && playwright install chromium")
        return
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=UA)
        if cookies:
            host = re.sub(r"^https?://([^/]+).*", r"\1", url)
            ctx.add_cookies([{"name": c.split("=", 1)[0].strip(), "value": c.split("=", 1)[1].strip(),
                              "domain": host, "path": "/"} for c in cookies.split(";") if "=" in c])
        page = ctx.new_page()
        resp = page.goto(url, wait_until="networkidle", timeout=45000)
        report("browser", resp.status if resp else "?", "text/html", page.content())
        b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--cookies", default="")
    a = ap.parse_args()
    plain(a.url, a.cookies)
    if a.browser:
        browser(a.url, a.cookies)

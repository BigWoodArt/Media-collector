"""Let the user pass a site's bot check in a real browser window, then reuse that session's cookies.
Primary path: no extra packages. Launches the installed Chrome or Edge with its own profile (browser_profile/) and a
local debugging port, and talks to it with a tiny built-in WebSocket client. Nothing is automated on the page: the
window opens the site and waits while YOU pass the check. Fallback (no Chrome/Edge): optional Playwright + its own
Chromium, installed from a Settings button (install_fallback())."""
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.request

from core import settings

PROFILE_DIR = settings.APP_DIR / "browser_profile"
CHANNELS = ("chrome", "msedge", None)       # None = Playwright's bundled Chromium
CHECK_MARKERS = ("not a bot", "just a moment", "checking your browser", "verify you are human")


class BrowserSessionError(RuntimeError):
    pass


def find_browser():
    """Path of an installed Chrome or Edge, or None."""
    env = os.environ
    cands = []
    if sys.platform.startswith("win"):
        for base in (env.get("PROGRAMFILES"), env.get("PROGRAMFILES(X86)"), env.get("LOCALAPPDATA")):
            if base:
                cands += [os.path.join(base, r"Google\Chrome\Application\chrome.exe"),
                          os.path.join(base, r"Microsoft\Edge\Application\msedge.exe")]
    elif sys.platform == "darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    else:
        cands = [shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chrome", "chromium",
                                           "chromium-browser", "microsoft-edge", "microsoft-edge-stable")]
    return next((c for c in cands if c and os.path.isfile(c)), None)


def playwright_available():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def cookie_header(cookies, host):
    """Playwright cookie dicts -> 'a=b; c=d' for the cookies that apply to host."""
    host = host.lower()
    parts = []
    for c in cookies:
        dom = (c.get("domain") or "").lstrip(".").lower()
        if dom and (host == dom or host.endswith("." + dom)):
            parts.append(f"{c['name']}={c['value']}")
    return "; ".join(parts)


def looks_passed(html, ok_marker):
    low = (html or "").lower()
    return ok_marker in low and not any(m in low for m in CHECK_MARKERS if m not in ok_marker)


class _WS:
    """Minimal client-side WebSocket (text frames) for the browser's DevTools port."""
    def __init__(self, host, port, path, timeout=10):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise BrowserSessionError("Browser refused the debug connection.")
            buf += chunk
        if b" 101 " not in buf.split(b"\r\n", 1)[0]:
            raise BrowserSessionError("Browser refused the debug connection.")
        self.rest = buf.split(b"\r\n\r\n", 1)[1]
        self.id = 0

    def _read(self, n):
        while len(self.rest) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise BrowserSessionError("Browser closed.")
            self.rest += chunk
        out, self.rest = self.rest[:n], self.rest[n:]
        return out

    def _send(self, data, opcode=1):
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x80 | opcode])
        head += (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536
                 else bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _recv(self):
        msg = b""
        while True:
            b1, b2 = self._read(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            data = self._read(n)
            op = b1 & 0x0F
            if op == 8:
                raise BrowserSessionError("Browser closed.")
            if op == 9:
                self._send(data, 10)
                continue
            if op in (1, 0, 2):
                msg += data
                if b1 & 0x80:
                    return msg.decode("utf-8", "replace")

    def call(self, method, params=None):
        self.id += 1
        self._send(json.dumps({"id": self.id, "method": method, "params": params or {}}).encode())
        while True:
            m = json.loads(self._recv())
            if m.get("id") == self.id:
                if "error" in m:
                    raise BrowserSessionError(m["error"].get("message", "debug error"))
                return m.get("result", {})

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def _page_state(ws):
    r = ws.call("Runtime.evaluate", {"expression": "document.title+'\\n'+(document.body?document.body.innerText.slice(0,4000):'')"
                                                    "+'\\n'+(document.querySelector('.thumb_square,#header,.navbar')?'SITE_OK':'')",
                                     "returnByValue": True})
    return r.get("result", {}).get("value", "") or ""


def capture_system(url, host, ok_marker, status=lambda msg: None, timeout=300, cancelled=lambda: False):
    exe = find_browser()
    if not exe:
        raise BrowserSessionError("No Chrome or Edge found.")
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    port_file = PROFILE_DIR / "DevToolsActivePort"
    try:
        port_file.unlink()
    except OSError:
        pass
    proc = subprocess.Popen([exe, f"--user-data-dir={PROFILE_DIR}", "--remote-debugging-port=0",
                             "--remote-allow-origins=*", "--no-first-run", "--no-default-browser-check", url],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    try:
        end = time.time() + 30
        while not port_file.exists() and time.time() < end:
            if proc.poll() is not None:
                raise BrowserSessionError("Browser closed immediately. Close any other window using the "
                                          "Media Collector browser profile and retry.")
            time.sleep(0.3)
        if not port_file.exists():
            raise BrowserSessionError("Browser didn't start its debug port.")
        time.sleep(0.3)
        port = int(port_file.read_text().splitlines()[0])
        status("Browser open - pass the check if it appears...")
        end = time.time() + timeout
        while time.time() < end:
            if cancelled():
                raise BrowserSessionError("Cancelled.")
            if proc.poll() is not None:
                raise BrowserSessionError("Browser window was closed before the check was passed.")
            try:
                if ws is None:
                    tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5).read())
                    tab = next((t for t in tabs if t.get("type") == "page"), None)
                    if tab:
                        ws = _WS("127.0.0.1", port, "/devtools/page/" + tab["id"])
                if ws:
                    state = _page_state(ws)
                    if looks_passed(state, ok_marker):
                        ua = ws.call("Runtime.evaluate", {"expression": "navigator.userAgent",
                                                           "returnByValue": True})["result"]["value"]
                        ws.call("Network.enable")
                        header = cookie_header(ws.call("Network.getAllCookies").get("cookies", []), host)
                        if header:
                            return {"cookie": header, "user_agent": ua}
            except BrowserSessionError:
                if ws:
                    ws.close()
                ws = None       # tab navigated/closed; reattach
            except (OSError, ValueError):
                ws = None
            time.sleep(1)
        raise BrowserSessionError("Timed out waiting for the bot check to be passed.")
    finally:
        if ws:
            ws.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()


def install_fallback(log=lambda m: None):
    """For PCs without Chrome/Edge: pip install playwright + download its Chromium."""
    for cmd in ([sys.executable, "-m", "pip", "install", "playwright"],
                [sys.executable, "-m", "playwright", "install", "chromium"]):
        log(" ".join(cmd[2:]))
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            raise BrowserSessionError((r.stderr or r.stdout).strip().splitlines()[-1][:200])


def capture_playwright(url, host, ok_marker, status=lambda msg: None, timeout=300, cancelled=lambda: False):
    """Open url in a visible browser; return {"cookie": header, "user_agent": ua} once the page past the bot check
    (its HTML contains ok_marker) has loaded. Raises BrowserSessionError on failure/timeout/cancel."""
    try:
        from playwright.sync_api import sync_playwright, Error as PWError
    except ImportError:
        raise BrowserSessionError("Playwright isn't installed. Run: pip install playwright")
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx, last = None, None
        for ch in CHANNELS:
            try:
                kw = {"channel": ch} if ch else {}
                ctx = pw.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False, **kw)
                break
            except PWError as ex:
                last = ex
        if ctx is None:
            raise BrowserSessionError("Couldn't open a browser. Install Chrome or Edge, or run: "
                                      f"python -m playwright install chromium ({str(last).splitlines()[0] if last else ''})")
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except PWError:
                pass        # a challenge page may keep loading; keep polling
            status("Browser open - pass the check if it appears...")
            end = time.time() + timeout
            while time.time() < end:
                if cancelled():
                    raise BrowserSessionError("Cancelled.")
                try:
                    if looks_passed(page.content(), ok_marker):
                        ua = page.evaluate("navigator.userAgent")
                        header = cookie_header(ctx.cookies(), host)
                        if header:
                            return {"cookie": header, "user_agent": ua}
                except PWError:
                    pass    # page navigating
                if not ctx.pages:
                    raise BrowserSessionError("Browser window was closed before the check was passed.")
                time.sleep(1)
            raise BrowserSessionError("Timed out waiting for the bot check to be passed.")
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def capture(url, host, ok_marker, **kw):
    if find_browser():
        return capture_system(url, host, ok_marker, **kw)
    if playwright_available():
        return capture_playwright(url, host, ok_marker, **kw)
    raise BrowserSessionError("NEED_FALLBACK")


def capture_hentai_foundry(**kw):
    return capture("https://www.hentai-foundry.com/", "hentai-foundry.com", "hentai foundry", **kw)


def capture_rule34(**kw):
    return capture("https://rule34.xxx/", "rule34.xxx", "rule34", **kw)

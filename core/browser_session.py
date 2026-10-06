"""Sign in to a site that shows a bot check, in a real browser window, then reuse that browser session.

You open the site yourself in a separate Chrome/Edge window that uses its own profile folder (nothing from your
everyday browser profile is read), pass the check like any visitor, and press Save. The program then asks that window
for the site's cookies and its user-agent text, and sends the same ones with its own requests. Nothing is solved or
faked by the program, and the browser is only reachable from this computer while the window is open."""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

from core.miniws import WebSocket, WSError


def find_browser():
    """Path of an installed Chrome / Edge / Chromium, or None."""
    cands = []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LocalAppData")):
            if base:
                cands += [os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                          os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(base, "Chromium", "Application", "chrome.exe")]
    elif sys.platform == "darwin":
        cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "chrome"):
        p = shutil.which(name)
        if p:
            cands.append(p)
    return next((c for c in cands if c and os.path.exists(c)), None)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BrowserSession:
    def __init__(self, profile_dir, browser=None):
        self.profile_dir = profile_dir
        self.browser = browser or find_browser()
        self.port, self.proc = None, None

    @property
    def running(self):
        return bool(self.proc and self.proc.poll() is None)

    def open(self, url, extra_args=()):
        if not self.browser:
            raise WSError("No Chrome, Edge or Chromium was found on this computer.")
        os.makedirs(self.profile_dir, exist_ok=True)
        self.port = _free_port()
        args = [self.browser, f"--remote-debugging-port={self.port}", "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={self.profile_dir}", "--no-first-run", "--no-default-browser-check",
                *extra_args, url]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 20
        while time.time() < deadline:
            if not self.running:
                raise WSError("The browser closed straight away (is another window using the same profile?).")
            try:
                self._version()
                return
            except OSError:
                time.sleep(0.3)
        raise WSError("The browser didn't answer in time.")

    def _version(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=3) as r:
            return json.loads(r.read().decode())

    def grab(self, domain_suffix):
        """-> (cookie_header, user_agent) for cookies whose domain ends with domain_suffix."""
        info = self._version()
        ws = WebSocket(info["webSocketDebuggerUrl"])
        try:
            cookies = ws.call("Storage.getCookies").get("cookies", [])
        finally:
            ws.close()
        want = domain_suffix.lstrip(".").lower()
        mine = [c for c in cookies if c.get("domain", "").lstrip(".").lower().endswith(want)]
        header = "; ".join(f"{c['name']}={c['value']}" for c in mine)
        ua = info.get("User-Agent", "")
        return header, ua

    def close(self):
        if self.running:
            try:
                ws = WebSocket(self._version()["webSocketDebuggerUrl"])
                try:
                    ws.call("Browser.close")
                finally:
                    ws.close()
            except (OSError, ValueError):
                pass
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.terminate()

"""Drives a real Chromium if one is installed (skipped otherwise): load a local page that sets cookies, then read
them back through the DevTools channel exactly as the Settings 'Save session' button does."""
import http.server
import tempfile
import threading
import unittest

from core.browser_session import BrowserSession, find_browser


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Set-Cookie", "pass=abc123; HttpOnly; Path=/")
        self.send_header("Set-Cookie", "other=xyz; Path=/")
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html>ok</html>")

    def log_message(self, *a):
        pass


@unittest.skipUnless(find_browser() or __import__("os").path.exists("/opt/pw-browsers/chromium"), "no Chromium")
class RealBrowser(unittest.TestCase):
    def test_reads_httponly_cookies_and_user_agent(self):
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        s = BrowserSession(tempfile.mkdtemp(), browser=find_browser() or "/opt/pw-browsers/chromium")
        try:
            s.open(f"http://127.0.0.1:{srv.server_port}/", extra_args=("--headless=new", "--no-sandbox", "--disable-gpu"))
            import time
            for _ in range(20):
                header, ua = s.grab("127.0.0.1")
                if "pass=abc123" in header:
                    break
                time.sleep(0.5)
        finally:
            s.close()
            srv.shutdown()
        self.assertIn("pass=abc123", header)            # HttpOnly cookie is included
        self.assertIn("other=xyz", header)
        self.assertIn("Mozilla", ua)
        self.assertFalse(s.running)


if __name__ == "__main__":
    unittest.main()

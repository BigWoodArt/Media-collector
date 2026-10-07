import urllib.request

from sources.booru_family import BooruFamilySource


class Rule34Source(BooruFamilySource):
    """rule34.xxx - API credentials are preferred; an optional browser session
    can be used for the site's own search when it presents a CAPTCHA."""
    id, label = "rule34", "Rule34"
    check_query = "cat_ears"
    base_url = "https://api.rule34.xxx"
    site_url = "https://rule34.xxx"
    prefix = "r34_"
    api_policy = "key"
    api_key_helps = True

    def __init__(self, api_key="", user_id="", cookie="", user_agent=""):
        super().__init__(api_key, user_id)
        self.cookie = cookie.strip()
        self.user_agent = user_agent.strip() or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"

    def _browser_headers(self):
        h = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": self.site_url + "/",
        }
        if self.cookie:
            h["Cookie"] = self.cookie
        return h

    def _get_text(self, url, timeout=15):
        self._wait()
        req = urllib.request.Request(url, headers=self._browser_headers())
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")

    def _get_bytes(self, url, timeout=30):
        self._wait()
        h = self._browser_headers()
        h["Referer"] = self.site_url + "/"
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()


class SafebooruSource(BooruFamilySource):
    id, label = "safebooru", "Safebooru"
    check_query = "cat_ears"
    base_url = "https://safebooru.org"
    prefix = "sb_"


class TbibSource(BooruFamilySource):
    id, label = "tbib", "TBIB"
    check_query = "cat_ears"
    base_url = "https://tbib.org"
    prefix = "tb_"


class XbooruSource(BooruFamilySource):
    id, label = "xbooru", "Xbooru"
    check_query = "cat_ears"
    base_url = "https://xbooru.com"
    prefix = "xb_"

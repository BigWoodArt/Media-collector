"""Update check: reads APP_VERSION from the project's settings.py on GitHub. One small request, at start-up."""
import re
import urllib.request

REPO = "BigWoodArt/Media-collector"
PAGE_URL = f"https://github.com/{REPO}"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/main/app/core/settings.py"


def parse_version(text):
    """'APP_VERSION = "0.1.12"' somewhere in text -> (0, 1, 12), or None."""
    m = re.search(r'APP_VERSION\s*=\s*"(\d+(?:\.\d+)*)"', text or "")
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def latest_version(timeout=6):
    """The version on GitHub as a tuple, or None if it can't be read. Never raises."""
    try:
        req = urllib.request.Request(VERSION_URL, headers={"User-Agent": "MediaCollector-update-check"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return parse_version(resp.read(65536).decode("utf-8", "replace"))
    except Exception:
        return None


def newer_available(current, fetch=latest_version):
    """'0.1.12' if GitHub has a newer release than `current` (a 'x.y.z' string), else None."""
    latest, mine = fetch(), parse_version(f'APP_VERSION = "{current}"')
    if latest and mine and latest > mine:
        return ".".join(map(str, latest))
    return None

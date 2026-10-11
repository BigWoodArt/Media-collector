"""Built-in content guard: posts whose tags/text point to minors are always skipped.
Not configurable on purpose - this tool is for adult material only."""
import re

_EXACT = {"cub", "cubs", "young", "minor", "minors", "underage", "preteen", "pre-teen", "baby",
          "infant", "kid", "kids"}
_PREFIX = ("loli", "shota", "toddler", "child", "underage", "schoolkid", "elementary_school")
_WORD_RE = re.compile(r"[a-z0-9_\-]+")


def _tokens(text):
    return _WORD_RE.findall((text or "").lower().replace(" ", " "))


def is_blocked(tags):
    """tags: iterable of tag strings, or one string of space-separated tags / free text."""
    if isinstance(tags, str):
        tags = _tokens(tags)
    for t in tags:
        t = (t or "").lower().strip()
        if t in _EXACT or t.startswith(_PREFIX):
            return True
    return False


def query_blocked(query):
    """True when a search query itself asks for blocked material."""
    return is_blocked(_tokens(query))

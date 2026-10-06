from sources.booru_family import BooruFamilySource


class HypnohubSource(BooruFamilySource):
    """Gelbooru-style API, then the website pages."""
    id, label = "hypnohub", "HypnoHub"
    check_query = "spiral"
    base_url = "https://hypnohub.net"
    prefix = "hh_"
    query_hint = "tags (e.g. spiral)"

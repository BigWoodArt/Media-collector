from sources.booru_family import BooruFamilySource


class HypnohubSource(BooruFamilySource):
    """Gelbooru-style API, then the website pages."""
    id, label = "hypnohub", "HypnoHub"
    check_query = "spiral"
    base_url = "https://hypnohub.net"
    prefix = "hh_"
    quality_scores = {"Good": 5, "Best": 20}
    query_hint = "tags (e.g. spiral)"

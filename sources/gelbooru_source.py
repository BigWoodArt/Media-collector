from sources.booru_family import BooruFamilySource


class GelbooruSource(BooruFamilySource):
    """Works without an account: if its API refuses, the website pages are used."""
    id, label = "gelbooru", "Gelbooru"
    check_query = "cat_ears"
    base_url = "https://gelbooru.com"
    prefix = "gb_"
    quality_scores = {"Good": 10, "Best": 50}
    api_key_helps = True
    api_policy = "key"        # anonymous dapi answers HTTP 401 (seen in real runs)

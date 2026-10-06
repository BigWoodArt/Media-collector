from sources.booru_family import BooruFamilySource


class Rule34Source(BooruFamilySource):
    """rule34.xxx - its API may want a key; the website pages are the fallback."""
    id, label = "rule34", "Rule34"
    check_query = "cat_ears"
    base_url = "https://api.rule34.xxx"
    site_url = "https://rule34.xxx"
    prefix = "r34_"
    api_policy = "key"        # anonymous API answers "Missing authentication"
    api_key_helps = True


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

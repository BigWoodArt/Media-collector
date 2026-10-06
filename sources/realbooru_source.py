from sources.booru_family import BooruFamilySource


class RealbooruSource(BooruFamilySource):
    id, label = "realbooru", "RealBooru"
    check_query = "cute"
    base_url = "https://realbooru.com"
    prefix = "rb_"
    api_policy = "off"        # dapi answers "API offline ... shut off indefinitely"

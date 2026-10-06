class Source:
    """Base interface for a scraper plugin. Subclasses implement fetch()."""
    id = "base"
    label = "Base"
    query_hint = "query"
    default_limit = 20
    category = "Other"          # groups sites in the picker
    # Sort dropdown: (key, label, params); params = any of {"sort", "time_range", "query_suffix"}.
    order_choices = []
    default_order = ""
    min_score_choices = []      # optional second dropdown (boorus), same shape
    order_help = "How results are ordered. Choices differ per site."
    default_randomize = False   # Random box starts ticked
    priority_media = "image"    # what Prioritize favours: "image" or "video"
    default_prioritize = False  # Prioritize box starts ticked
    check_query = "test"        # harmless query for Check all sites
    has_media_priority = False  # yields both images and videos (shows the Prioritize box)

    def fetch(self, query, limit, sort, time_range, dest_dir, log, progress, stop_event,
              early_preview_cb=None, randomize=False, prioritize_images=False,
              item_cb=None, skip_ids=None):
        """Runs off the main thread; returns [MediaItem]. log(msg, level) and progress(cur, total, prefix) are thread-safe;
        check stop_event often. early_preview_cb(items) is called once at ~3 items; item_cb(item) for every kept file.
        randomize shuffles before the limit applies. skip_ids = post_ids already collected (skip before downloading).
        prioritize_images softly favours priority_media (about 4 of that kind per 1 other)."""
        raise NotImplementedError

    @classmethod
    def suggest(cls, query):
        """Optional: real matches for a keyword from the site itself, for a pick-list in the UI.
        Returns [{"value": text to search, "label": display, "count": int or None}]; [] when unsupported. Never raises."""
        return []

    @classmethod
    def resolve(cls, order="", min_score=""):
        """Choice keys -> {'sort', 'time_range', 'query_suffix'} ('' = site default / no minimum)."""
        out, suffixes = {}, []
        for choices, key in ((cls.order_choices, order or cls.default_order), (cls.min_score_choices, min_score)):
            params = next((p for k, _, p in choices if k == key), {})
            for name, value in params.items():
                if name == "query_suffix":
                    suffixes.append(value)
                else:
                    out[name] = value
        if suffixes:
            out["query_suffix"] = " ".join(suffixes)
        return out

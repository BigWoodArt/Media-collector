class Source:
    """Base interface for a scraper plugin. Subclasses implement fetch()."""
    id = "base"
    label = "Base"
    query_hint = "query"
    has_sort = False
    has_time = True  # shown only when has_sort
    sort_options = []
    time_options = []
    default_sort = ""
    default_limit = 20
    category = "Other"          # groups sites in the picker
    supports_quality = False    # resolve_quality() applies
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
        """Optional: real matches for a keyword from the site itself, so the UI can show tickable chips.
        Returns [{"value": text to search, "label": display, "count": int or None}]; [] when unsupported.
        Must be fast, never raise, and use only the site's own lookup (no guessing)."""
        return []

    @classmethod
    def resolve_quality(cls, quality):
        """Map Any/Good/Best to this site's controls: {'sort', 'time_range', 'query_suffix'}; {} = nothing."""
        return {}

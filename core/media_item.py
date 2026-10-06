from dataclasses import dataclass, field


@dataclass
class MediaItem:
    file_path: str          # absolute path on disk
    caption: str            # Reddit post title, used as pack caption
    media_type: str         # "image", "video" or "audio"
    source_label: str = ""  # e.g. "r/cats via Reddit RSS"
    post_id: str = ""       # dedupe key
    source_type: str = ""   # which scraper found it
    attribution: str = ""   # credit line for CREDITS.txt
    extra: dict = field(default_factory=dict)   # source facts for the run log

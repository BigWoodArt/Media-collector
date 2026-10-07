SOURCES_VERSION = "2026.10.07.1"   # bump on any change to the shared scraper files

from sources.reddit_source import RedditSource
from sources.redgifs_source import RedgifsSource
from sources.soundgasm_source import SoundgasmSource
from sources.freesound_source import FreesoundSource
from sources.erome_source import EromeSource
from sources.gelbooru_source import GelbooruSource
from sources.realbooru_source import RealbooruSource
from sources.hypnohub_source import HypnohubSource
from sources.booru_extra_sources import Rule34Source, SafebooruSource, TbibSource, XbooruSource
from sources.e621_source import E621Source
from sources.danbooru_source import DanbooruSource
from sources.moebooru_sources import YandereSource, KonachanSource
from sources.derpibooru_source import DerpibooruSource
from sources.wallhaven_source import WallhavenSource
from sources.civitai_source import CivitaiSource   # kept for later; see DISABLED below
from sources.lemmy_source import LemmySource
from sources.sexcom_source import SexComPicsSource, SexComGifsSource
from sources.hentaifoundry_source import HentaiFoundrySource
from sources.kemono_source import KemonoSource
from sources.coomer_source import CoomerSource
from sources.fapello_source import FapelloSource

SOURCE_CLASSES = [RedditSource, RedgifsSource, SoundgasmSource, FreesoundSource, EromeSource,
                  GelbooruSource, RealbooruSource, HypnohubSource,
                  Rule34Source, SafebooruSource, TbibSource, XbooruSource,
                  E621Source, DanbooruSource, YandereSource, KonachanSource, DerpibooruSource,
                  WallhavenSource, LemmySource,
                  SexComPicsSource, SexComGifsSource, HentaiFoundrySource,
                  KemonoSource, CoomerSource, FapelloSource]
# Civitai is switched off: image search has been down and public search returns models, not tagged images.
DISABLED_SOURCE_CLASSES = [CivitaiSource]
SOURCE_BY_LABEL = {c.label: c for c in SOURCE_CLASSES}
SOURCE_LABELS = [c.label for c in SOURCE_CLASSES]
SOURCE_BY_ID = {c.id: c for c in SOURCE_CLASSES}
CATEGORIES = sorted({c.category for c in SOURCE_CLASSES})

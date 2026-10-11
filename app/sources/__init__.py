SOURCES_VERSION = "2026.10.11.1"   # bump on any change to the shared scraper files

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
from sources.lemmy_source import LemmySource
from sources.sexcom_source import SexComPicsSource, SexComGifsSource
from sources.hentaifoundry_source import HentaiFoundrySource
from sources.kemono_source import KemonoSource
from sources.coomer_source import CoomerSource
from sources.fapello_source import FapelloSource
from sources.pmvhaven_source import PmvHavenSource
from sources.hypnotube_source import HypnoTubeSource

SOURCE_CLASSES = [RedditSource, RedgifsSource, SoundgasmSource, FreesoundSource, EromeSource,
                  GelbooruSource, RealbooruSource, HypnohubSource,
                  Rule34Source, SafebooruSource, TbibSource, XbooruSource,
                  E621Source, DanbooruSource, YandereSource, KonachanSource, DerpibooruSource,
                  WallhavenSource, LemmySource,
                  SexComPicsSource, SexComGifsSource, HentaiFoundrySource,
                  KemonoSource, CoomerSource, FapelloSource,
                  PmvHavenSource, HypnoTubeSource]
SOURCE_BY_ID = {c.id: c for c in SOURCE_CLASSES}


# The picker lists sites under these headings (a site not named here goes under "Other", last).
SOURCE_GROUPS = [
    ("Image boards", ["gelbooru", "realbooru", "hypnohub", "rule34", "safebooru", "tbib", "xbooru",
                      "e621", "danbooru", "yandere", "konachan", "derpibooru"]),
    ("Video", ["pmvhaven", "hypnotube", "redgifs", "sexcom_gifs"]),
    ("Image / mixed", ["reddit", "wallhaven", "hentaifoundry", "sexcom_pics", "kemono", "coomer", "fapello",
                       "erome", "lemmy"]),
    ("Audio", ["soundgasm", "freesound"]),
]


def grouped_sources():
    """[(heading, [source class, ...])] in picker order; every enabled site appears exactly once."""
    out, used = [], set()
    for name, ids in SOURCE_GROUPS:
        members = [SOURCE_BY_ID[i] for i in ids if i in SOURCE_BY_ID]
        used.update(c.id for c in members)
        if members:
            out.append((name, members))
    rest = [c for c in SOURCE_CLASSES if c.id not in used]
    if rest:
        out.append(("Other", rest))
    return out

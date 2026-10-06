"""App settings (plain JSON next to the program) and the per-site credential fields shown in Settings."""
import json
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
SETTINGS_FILE = APP_DIR / "collector_settings.json"

# (site id, constructor argument, label, help). Site ids match sources/*.id.
CRED_FIELDS = [
    ("reddit", None, None, None),
    ("e621", "user_id", "e621 username", "Optional. With an API key it lifts limits and shows more posts."),
    ("e621", "api_key", "e621 API key", "Optional. Account > Manage API access."),
    ("danbooru", "user_id", "Danbooru username", "Optional. Free anonymous searches are limited to 2 tags."),
    ("danbooru", "api_key", "Danbooru API key", "Optional. Profile > API keys."),
    ("gelbooru", "user_id", "Gelbooru user ID", "Optional. Both ID and key together enable the faster API."),
    ("gelbooru", "api_key", "Gelbooru API key", "Optional."),
    ("rule34", "user_id", "Rule34 user ID", "Optional. Both ID and key together enable the faster API."),
    ("rule34", "api_key", "Rule34 API key", "Optional."),
    ("wallhaven", "api_key", "Wallhaven API key", "Free, from account settings. Needed for NSFW results."),
    ("civitai", "api_key", "Civitai API key", "Required. civitai.red needs a login API key."),
    ("civitai", "base_url", "Civitai address", "Default https://civitai.red. Change only if the site moves."),
    ("lemmy", "api_key", "Lemmy login token", "Your account's JWT. Needed to see NSFW posts."),
    ("lemmy", "instance", "Lemmy home instance", "e.g. lemmy.world - where your account lives."),
    ("freesound", "api_key", "Freesound API key", "Free, from freesound.org/apiv2/apply."),
]
CRED_FIELDS = [f for f in CRED_FIELDS if f[1]]

DEFAULTS = {
    "output_dir": str(APP_DIR / "collections"),
    "last_collection": "My collection",
    "limit": 50,
    "quality": "Good",
    "types": ["image", "video"],
    "randomize": False,
    "credentials": {},      # {site id: {argument: value}}
    "recent_sources": [],
}


def load():
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            data.update(saved)
    except (OSError, ValueError):
        pass
    if not isinstance(data.get("credentials"), dict):
        data["credentials"] = {}
    return data


def save(data):
    tmp = str(SETTINGS_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, SETTINGS_FILE)


def credentials_for(data):
    """{site: {arg: value}} with empty values dropped, ready for Source(**creds)."""
    out = {}
    for site, args in (data.get("credentials") or {}).items():
        clean = {k: str(v).strip() for k, v in (args or {}).items() if str(v).strip()}
        if clean:
            out[site] = clean
    return out

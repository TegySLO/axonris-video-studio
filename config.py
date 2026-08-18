"""config.py -- local, per-user settings for Axonris Video Studio.
Same atomic-write pattern as axonris-sub-engine/onboarding_wizard.py's
save_config()/load_config() (temp file + os.replace(), so a crash mid-write
never corrupts the file) and axonris-hub/config.py's LOCALAPPDATA-based
data dir (so the module's settings live next to itself, per-user, not in
the repo)."""
from __future__ import annotations
import json
import os


def get_data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    d = os.path.join(base, "AxonrisVideoStudio")
    os.makedirs(d, exist_ok=True)
    return d


def get_config_path() -> str:
    return os.path.join(get_data_dir(), "config.json")


def load_config() -> dict:
    path = get_config_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(fields: dict) -> None:
    existing = load_config()
    existing.update(fields)
    path = get_config_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

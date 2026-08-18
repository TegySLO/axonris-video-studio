"""project_settings.py -- per-project settings for Axonris Video Studio.
Same .axonris/-folder-lives-with-the-project convention as
axonris-sub-engine/plan_builder.py (this repo is standalone/public, so it
reimplements the convention rather than importing the private module)."""
from __future__ import annotations
import json
import os

_DEFAULTS = {
    "template_id": None,
    "zoom_style": "moderate",   # matches Pot B's OpenScreen-derived zoom setting (Task 1 of the follow-up recording-pipeline plan)
    "use_trimmer": False,       # seedprod-style dead-time trimmer, only meaningful for Claude Code/Forge session recordings
}

_REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "registry.json")


def _settings_path(project_path: str) -> str:
    return os.path.join(project_path, ".axonris", "video_studio_settings.json")


def load_settings(project_path: str) -> dict:
    path = _settings_path(project_path)
    if not os.path.exists(path):
        return dict(_DEFAULTS)
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
    except Exception:
        return dict(_DEFAULTS)
    merged = dict(_DEFAULTS)
    merged.update(saved)
    return merged


def save_settings(project_path: str, settings: dict) -> None:
    existing = load_settings(project_path)
    existing.update(settings)
    path = _settings_path(project_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def list_templates() -> list:
    with open(_REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)["templates"]

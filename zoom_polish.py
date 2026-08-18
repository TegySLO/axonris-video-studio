"""zoom_polish.py -- cursor-driven auto-zoom, reimplementing the
DOCUMENTED APPROACH of EtienneLescot/openscreen (auto-zoom on click,
cursor smoothing) via ffmpeg filters -- not a port of its Electron/
TypeScript code, which doesn't run in this Python/PySide6 codebase.
Zoom style ("moderate"/"aggressive") reads from project_settings.py's
existing zoom_style field (Foundation plan Task 5) -- callers pass it in,
this module doesn't read project_settings.py directly (keeps this module
usable standalone/tested without a project context)."""
from __future__ import annotations
import subprocess

import imageio_ffmpeg

from screen_recorder import RecordingSession

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

_CLUSTER_GAP_SEC = 2.0  # clicks closer together than this collapse into one zoom target


def find_zoom_targets(cursor_log: list[dict]) -> list[dict]:
    """Groups clicks that happen close together in time into one zoom
    target (the first click's position/time in each cluster) -- avoids a
    jittery zoom-in/zoom-out/zoom-in for a rapid double-click or drag."""
    clicks = [e for e in cursor_log if e.get("click")]
    if not clicks:
        return []
    targets = [dict(clicks[0])]
    for entry in clicks[1:]:
        if entry["t"] - targets[-1]["t"] > _CLUSTER_GAP_SEC:
            targets.append(dict(entry))
    return targets


def _zoom_scale_for_style(style: str) -> float:
    return {"moderate": 1.4, "aggressive": 1.9}.get(style, 1.4)


def apply_zoom(session: RecordingSession, output_path: str, style: str = "moderate") -> str:
    """Builds an ffmpeg zoompan filter that zooms toward each click target
    for a few seconds, then back out. Falls back to a straight re-encode
    (no zoom) when there are no click targets, so this never fails on a
    clip with no recorded clicks (e.g. a pure narration screen)."""
    targets = find_zoom_targets(session.cursor_log)
    scale = _zoom_scale_for_style(style)

    if not targets:
        cmd = [
            FFMPEG, "-y", "-i", session.raw_video_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
    else:
        # One zoompan expression per target, zooming in around (x,y) between
        # t and t+2.5s then back to 1.0 -- a simple Ken-Burns-style pulse per
        # click, not a full pan/tilt system (that's a v2 refinement, not
        # needed for the "tutorial gets a bit more polish" goal here).
        zoom_expr_parts = []
        for target in targets:
            t0, t1 = target["t"], target["t"] + 2.5
            zoom_expr_parts.append(
                f"if(between(t,{t0},{t1}),{scale},1)"
            )
        zoom_expr = "+".join(zoom_expr_parts) if len(zoom_expr_parts) > 1 else zoom_expr_parts[0]
        filter_str = f"zoompan=z='{zoom_expr}':d=1:s=hd1080"
        cmd = [
            FFMPEG, "-y", "-i", session.raw_video_path,
            "-vf", filter_str,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            output_path,
        ]

    subprocess.run(cmd, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return output_path

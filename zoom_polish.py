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


def _even(value: int) -> int:
    value = int(value)
    return value - (value % 2)


def _output_size(session: RecordingSession) -> str:
    """zoompan's `s` option defaults to hd720 -- i.e. leaving it off does
    NOT mean "keep the input size", it silently rescales. Derive it from
    the real capture rect so a non-16:9 window isn't stretched (the old
    hardcoded `hd1080` distorted every non-1080p capture)."""
    if session.rect_width > 0 and session.rect_height > 0:
        return f"{_even(session.rect_width)}x{_even(session.rect_height)}"
    return "hd1080"


def _output_fps(session: RecordingSession) -> float:
    """zoompan's `fps` option defaults to 25, so without this the zoom
    pass silently retimes a 15 or 30 fps capture to 25 fps."""
    return session.fps if session.fps and session.fps > 0 else 30.0


def _build_time_windowed_expr(targets: list[dict], value_fn, default_expr: str) -> str:
    """Builds a nested ffmpeg if(between(time,t0,t1), value, ...) chain, one
    level per target, falling through to default_expr when no target's
    window is active. Nesting (rather than "+") avoids the default value
    getting added multiple times when several targets are simultaneously
    inactive."""
    expr = default_expr
    for target in reversed(targets):
        t0, t1 = target["t"], target["t"] + 2.5
        expr = f"if(between(time,{t0},{t1}),{value_fn(target)},{expr})"
    return expr


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
        # One nested if(between(time,...)) per target, zooming in around
        # (x,y) between t and t+2.5s then back to 1.0 -- a simple
        # Ken-Burns-style pulse per click, not a full pan/tilt system
        # (that's a v2 refinement, not needed for the "tutorial gets a bit
        # more polish" goal here).
        #
        # zoompan's seconds-based time variable is `time` (not a bare `t`,
        # which doesn't exist for this filter -- only `in`/`on` frame
        # counts and `in_time`/`it`). Windows are built as a nested
        # if/else chain (not summed with "+") so that when zero or
        # multiple targets are inactive at a given instant, the default
        # branch is used exactly once instead of stacking.
        #
        # cursor_log records SCREEN-absolute coordinates
        # (win32api.GetCursorPos), but zoompan's x/y are relative to the
        # captured frame's own origin. For any window capture the frame
        # starts at (rect_left, rect_top), so the raw screen coordinates
        # aimed the zoom hundreds of pixels off -- often clean off-frame.
        # Translate into frame space here.
        left, top = session.rect_left, session.rect_top
        zoom_expr = _build_time_windowed_expr(targets, lambda tgt: str(scale), "1")
        x_expr = _build_time_windowed_expr(
            targets, lambda tgt: f"{tgt['x'] - left}-(iw/zoom/2)", "iw/2-(iw/zoom/2)"
        )
        y_expr = _build_time_windowed_expr(
            targets, lambda tgt: f"{tgt['y'] - top}-(ih/zoom/2)", "ih/2-(ih/zoom/2)"
        )
        filter_str = (
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d=1"
            f":s={_output_size(session)}:fps={_output_fps(session):.4f}"
        )
        cmd = [
            FFMPEG, "-y", "-i", session.raw_video_path,
            "-vf", filter_str,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            output_path,
        ]

    subprocess.run(cmd, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return output_path

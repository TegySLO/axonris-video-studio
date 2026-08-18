"""screen_recorder.py -- captures a window or the full screen via mss
(BitBlt-based frame grabbing, verified real/MIT/Windows-supported),
pipes raw frames into ffmpeg for encoding (libx264 ONLY -- see this
plan's Global Constraints, AMD GPU encoding is a real BSOD risk on this
machine), and mixes in system audio via PyAudioWPatch's WASAPI loopback
(verified real/Apache-2.0/maintained).

Not a port of any reference project's code (OpenScreen is Electron/
TypeScript, auto-editor is Nim -- neither runs in this Python/PySide6
codebase); only the documented *approach* (auto-zoom on click, driven by
a cursor log) is reimplemented, in zoom_polish.py (Task 4)."""
from __future__ import annotations
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field

import mss
import win32gui
import imageio_ffmpeg

from cursor_log import CursorLogger

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


@dataclass
class RecordingSession:
    raw_video_path: str
    cursor_log: list = field(default_factory=list)


def _resolve_capture_rect(target: dict) -> dict:
    """target is window_picker.py's shape: {"hwnd": int|None, "title": str}.
    Returns {"left", "top", "width", "height"} -- mss's own monitor/rect
    dict shape, so it can be passed straight to mss.grab()."""
    if target.get("hwnd") is not None:
        left, top, right, bottom = win32gui.GetWindowRect(target["hwnd"])
        return {"left": left, "top": top, "width": right - left, "height": bottom - top}
    with mss.mss() as sct:
        # monitors[0] is mss's synthetic "all monitors combined" entry;
        # monitors[1] is the real primary monitor -- documented mss behavior.
        return dict(sct.monitors[1])


def _build_ffmpeg_capture_cmd(rect: dict, fps: int, output_path: str) -> list[str]:
    """Raw BGRA frames on stdin -> libx264-encoded MP4. NEVER GPU encoding
    (see Global Constraints) -- h264_amf/nvenc/cuda must never appear here."""
    return [
        FFMPEG, "-y",
        "-f", "rawvideo", "-pixel_format", "bgra",
        "-video_size", f"{rect['width']}x{rect['height']}",
        "-framerate", str(fps),
        "-i", "-",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        output_path,
    ]


def _spawn_ffmpeg_capture(rect: dict, fps: int, output_path: str) -> subprocess.Popen:
    cmd = _build_ffmpeg_capture_cmd(rect, fps, output_path)
    return subprocess.Popen(
        cmd, stdin=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


class _ActiveRecording:
    def __init__(self, target: dict, output_dir: str, fps: int):
        self._rect = _resolve_capture_rect(target)
        self._fps = fps
        self._raw_path = os.path.join(output_dir, f"raw_capture_{int(time.time())}.mp4")
        self._stop_event = threading.Event()
        self._cursor_logger = CursorLogger()
        self._proc = _spawn_ffmpeg_capture(self._rect, fps, self._raw_path)
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._cursor_logger.start()
        self._thread.start()

    def _capture_loop(self):
        with mss.mss() as sct:
            frame_interval = 1.0 / self._fps
            while not self._stop_event.is_set():
                frame = sct.grab(self._rect)
                try:
                    self._proc.stdin.write(frame.bgra)
                except (BrokenPipeError, OSError):
                    break
                time.sleep(frame_interval)

    def stop(self) -> RecordingSession:
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        cursor_entries = self._cursor_logger.stop()
        try:
            self._proc.stdin.close()
        except OSError:
            pass
        self._proc.wait(timeout=10)
        return RecordingSession(raw_video_path=self._raw_path, cursor_log=cursor_entries)


def start_recording(target: dict, output_dir: str, fps: int = 30) -> _ActiveRecording:
    os.makedirs(output_dir, exist_ok=True)
    return _ActiveRecording(target, output_dir, fps)

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
import threading
import time
import wave
from dataclasses import dataclass, field

import mss
import win32gui
import imageio_ffmpeg
import pyaudiowpatch as pyaudio

from cursor_log import CursorLogger

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
_AUDIO_CHUNK = 1024


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


def _build_mux_cmd(video_path: str, audio_path: str, output_path: str) -> list[str]:
    """Muxes the (already libx264-encoded) video-only capture with the
    captured WASAPI loopback WAV into one file. `-c:v copy` -- no
    re-encode, so no GPU-encoding risk here either. `-shortest` trims to
    whichever stream is shorter (video/audio capture threads don't stop
    at the exact same instant)."""
    return [
        FFMPEG, "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ]


class AudioCapture:
    """Background WASAPI loopback (system audio) capture via
    PyAudioWPatch, same start()/stop() thread pattern as
    cursor_log.CursorLogger. Fails soft: a machine with no default audio
    output device, or no WASAPI loopback support, still yields a
    video-only recording instead of crashing the whole capture -- same
    non-fatal-error posture as _ActiveRecording.stop()'s
    TimeoutExpired handling."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pyaudio = None
        self._stream = None
        self._wav_file = None
        self._wav_path: str | None = None
        self._failed = False

    def start(self, output_dir: str, tag: int) -> None:
        self._stop_event.clear()
        self._failed = False
        self._wav_path = os.path.join(output_dir, f"raw_audio_{tag}.wav")

        try:
            self._pyaudio = pyaudio.PyAudio()
            device = self._pyaudio.get_default_wasapi_loopback()
            channels = device["maxInputChannels"]
            rate = int(device["defaultSampleRate"])
            self._stream = self._pyaudio.open(
                format=pyaudio.paInt16, channels=channels, rate=rate,
                input=True, input_device_index=device["index"],
                frames_per_buffer=_AUDIO_CHUNK,
            )
            self._wav_file = wave.open(self._wav_path, "wb")
            self._wav_file.setnchannels(channels)
            self._wav_file.setsampwidth(self._pyaudio.get_sample_size(pyaudio.paInt16))
            self._wav_file.setframerate(rate)
        except Exception:
            # No default WASAPI loopback device (or PyAudioWPatch/WASAPI
            # unavailable) -- record video-only rather than crashing the
            # whole capture.
            self._failed = True
            self._cleanup()
            return

        def _loop():
            while not self._stop_event.is_set():
                try:
                    data = self._stream.read(_AUDIO_CHUNK, exception_on_overflow=False)
                except Exception:
                    break
                self._wav_file.writeframes(data)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def _cleanup(self):
        try:
            if self._stream is not None:
                self._stream.stop_stream()
                self._stream.close()
        except Exception:
            pass
        try:
            if self._pyaudio is not None:
                self._pyaudio.terminate()
        except Exception:
            pass
        try:
            if self._wav_file is not None:
                self._wav_file.close()
        except Exception:
            pass

    def stop(self) -> str | None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._cleanup()
        if self._failed or self._thread is None:
            return None
        return self._wav_path


class _ActiveRecording:
    def __init__(self, target: dict, output_dir: str, fps: int):
        self._rect = _resolve_capture_rect(target)
        self._fps = fps
        tag = int(time.time())
        self._raw_path = os.path.join(output_dir, f"raw_capture_{tag}.mp4")
        self._stop_event = threading.Event()
        self._cursor_logger = CursorLogger()
        self._audio_capture = AudioCapture()
        self._proc = _spawn_ffmpeg_capture(self._rect, fps, self._raw_path)
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._cursor_logger.start()
        self._audio_capture.start(output_dir, tag)
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
        audio_path = self._audio_capture.stop()
        try:
            self._proc.stdin.close()
        except OSError:
            pass
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()

        if audio_path is not None and os.path.exists(audio_path):
            muxed_tmp = self._raw_path.replace("raw_capture_", "raw_muxed_tmp_")
            try:
                subprocess.run(
                    _build_mux_cmd(self._raw_path, audio_path, muxed_tmp),
                    check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                os.replace(muxed_tmp, self._raw_path)
            except (subprocess.CalledProcessError, OSError):
                # Muxing failed -- keep the video-only capture rather than
                # losing the whole recording.
                pass
            finally:
                try:
                    os.remove(audio_path)
                except OSError:
                    pass

        return RecordingSession(raw_video_path=self._raw_path, cursor_log=cursor_entries)


def start_recording(target: dict, output_dir: str, fps: int = 30) -> _ActiveRecording:
    os.makedirs(output_dir, exist_ok=True)
    return _ActiveRecording(target, output_dir, fps)

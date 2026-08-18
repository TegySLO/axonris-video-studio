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
import wave
from dataclasses import dataclass, field

import mss
import win32gui
import imageio_ffmpeg
import pyaudiowpatch as pyaudio

from cursor_log import CursorLogger
from auto_cut import _probe_duration

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
_AUDIO_CHUNK = 1024

# Measured on this machine (RX 7800 XT / 1080p): a full-screen mss grab
# costs ~21 ms and the raw-BGRA pipe write ~2 ms, so ~40 fps is the hard
# ceiling and 30 fps leaves no headroom once the encoder is under load.
# 15 fps is comfortably sustainable and is plenty for a screen tutorial.
DEFAULT_FPS = 15

# Below this relative error we don't bother rewriting timestamps.
_RETIME_TOLERANCE = 0.02


def _even(value: int) -> int:
    """libx264 + yuv420p requires even frame dimensions; an odd-sized
    window (GetWindowRect returns arbitrary sizes) otherwise makes ffmpeg
    abort with "width not divisible by 2" the instant it starts."""
    value = int(value)
    return value - (value % 2)


@dataclass
class RecordingSession:
    raw_video_path: str
    cursor_log: list = field(default_factory=list)
    # Origin of the captured region in SCREEN coordinates. cursor_log
    # entries are screen-absolute (win32api.GetCursorPos), so consumers
    # must subtract this origin to get frame-relative coordinates.
    rect_left: int = 0
    rect_top: int = 0
    rect_width: int = 0
    rect_height: int = 0
    # Frames actually achieved per second, after timestamp correction --
    # NOT the requested fps. Consumers that re-encode must preserve this
    # or the result drifts against cursor_log's wall-clock timestamps.
    fps: float = float(DEFAULT_FPS)


def _resolve_capture_rect(target: dict) -> dict:
    """target is window_picker.py's shape: {"hwnd": int|None, "title": str}.
    Returns {"left", "top", "width", "height"} -- mss's own monitor/rect
    dict shape, so it can be passed straight to mss.grab(). Width/height
    are rounded DOWN to even values (libx264/yuv420p requirement)."""
    if target.get("hwnd") is not None:
        left, top, right, bottom = win32gui.GetWindowRect(target["hwnd"])
        return {
            "left": left, "top": top,
            "width": _even(right - left), "height": _even(bottom - top),
        }
    with mss.mss() as sct:
        # monitors[0] is mss's synthetic "all monitors combined" entry;
        # monitors[1] is the real primary monitor -- documented mss behavior.
        rect = dict(sct.monitors[1])
    rect["width"] = _even(rect["width"])
    rect["height"] = _even(rect["height"])
    return rect


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


def _spawn_ffmpeg_capture(rect: dict, fps: int, output_path: str, stderr_file=None) -> subprocess.Popen:
    cmd = _build_ffmpeg_capture_cmd(rect, fps, output_path)
    return subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stderr=stderr_file,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _build_retime_cmd(input_path: str, output_path: str, scale: float) -> list[str]:
    """Rewrites the capture's timestamps so the video's playback duration
    matches the wall-clock recording duration.

    The capture pipeline has to declare a framerate to ffmpeg BEFORE it
    knows what rate the machine will actually sustain, so the encoded file
    always claims the requested rate. `-itsscale` scales the input
    timestamps by requested/achieved, which is a pure STREAM COPY -- no
    re-encode, so no GPU-encoding risk here either. Without this the video
    plays back sped up and every cursor_log timestamp (wall-clock) lands
    outside the video's timeline, so no zoom ever fires."""
    return [
        FFMPEG, "-y",
        "-itsscale", f"{scale:.6f}",
        "-i", input_path,
        "-c", "copy",
        output_path,
    ]


def _build_mux_cmd(video_path: str, audio_path: str, output_path: str, video_duration: float) -> list[str]:
    """Muxes the (already libx264-encoded) video-only capture with the
    captured WASAPI loopback WAV into one file. `-c:v copy` -- no
    re-encode, so no GPU-encoding risk here either.

    `[1:a]apad=whole_dur=<video_duration>` pads the audio with silence to
    EXACTLY the video's real duration, given explicitly rather than left
    for `-shortest` to infer.

    BUG FIX (found via direct testing, not caught by any mocked test or
    review): an unbounded `apad[a]` (no whole_dur/pad_len) makes ffmpeg
    treat the audio stream as an infinite generator, and `-shortest`
    alone did not reliably terminate the encode against it -- confirmed
    live: 4 separate real test runs each left a real ffmpeg mux process
    hung indefinitely (`tasklist`/`wmic process` showed all 4 stuck on
    this exact command, never exiting on their own; had to `taskkill` all
    of them). Giving `apad` an explicit, finite target duration removes
    the ambiguity `-shortest` was apparently not resolving reliably in
    this filter_complex shape."""
    return [
        FFMPEG, "-y",
        "-i", video_path,
        "-i", audio_path,
        "-filter_complex", f"[1:a]apad=whole_dur={video_duration:.6f}[a]",
        "-map", "0:v:0", "-map", "[a]",
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
    TimeoutExpired handling. The reason for a soft failure is recorded on
    .last_error so callers can surface it instead of leaving a real setup
    problem indistinguishable from "this machine has no loopback device"."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pyaudio = None
        self._stream = None
        self._wav_file = None
        self._wav_path: str | None = None
        self._failed = False
        self.last_error: str | None = None

    def start(self, output_dir: str, tag: int) -> None:
        self._stop_event.clear()
        self._failed = False
        self.last_error = None
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
        except Exception as exc:
            # No default WASAPI loopback device (or PyAudioWPatch/WASAPI
            # unavailable) -- record video-only rather than crashing the
            # whole capture, but keep WHY so it isn't silent.
            self._failed = True
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._cleanup()
            return

        def _loop():
            while not self._stop_event.is_set():
                try:
                    data = self._stream.read(_AUDIO_CHUNK, exception_on_overflow=False)
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
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
        # time_ns, not int(time.time()): two recordings started within the
        # same second would otherwise share a tag and silently overwrite
        # each other's raw/zoomed/final outputs.
        tag = time.time_ns()
        self._raw_path = os.path.join(output_dir, f"raw_capture_{tag}.mp4")
        self._stop_event = threading.Event()
        self._cursor_logger = CursorLogger()
        self._audio_capture = AudioCapture()
        self._frame_count = 0
        self._capture_started_at = 0.0
        self._capture_ended_at = 0.0
        self._stderr_file = tempfile.NamedTemporaryFile(
            prefix="ffmpeg_capture_", suffix=".log", delete=False,
        )
        self._stderr_path = self._stderr_file.name
        self._proc = _spawn_ffmpeg_capture(
            self._rect, fps, self._raw_path, stderr_file=self._stderr_file,
        )
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._cursor_logger.start()
        self._audio_capture.start(output_dir, tag)
        self._thread.start()

    def _capture_loop(self):
        with mss.mss() as sct:
            frame_interval = 1.0 / self._fps
            self._capture_started_at = time.monotonic()
            next_deadline = self._capture_started_at
            while not self._stop_event.is_set():
                frame = sct.grab(self._rect)
                try:
                    self._proc.stdin.write(frame.bgra)
                except (BrokenPipeError, OSError):
                    break
                self._frame_count += 1
                # Deadline-based pacing: the grab + pipe write already cost
                # real time, so sleeping a flat frame_interval on top of
                # them yields far fewer frames per second than requested
                # (measured: 17.5 fps against a requested 30). Sleep only
                # the REMAINDER of this frame's slot, and when a frame has
                # already overrun its slot, re-base the deadline instead of
                # accumulating an ever-growing debt.
                next_deadline += frame_interval
                remaining = next_deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                else:
                    next_deadline = time.monotonic()
            self._capture_ended_at = time.monotonic()

    def _achieved_fps(self) -> float:
        elapsed = self._capture_ended_at - self._capture_started_at
        if elapsed <= 0 or self._frame_count <= 0:
            return float(self._fps)
        return self._frame_count / elapsed

    def _stderr_tail(self, max_chars: int = 800) -> str:
        try:
            with open(self._stderr_path, encoding="utf-8", errors="replace") as f:
                return f.read()[-max_chars:].strip()
        except OSError:
            return "(ffmpeg stderr unavailable)"

    def _discard_stderr_log(self) -> None:
        try:
            self._stderr_file.close()
        except OSError:
            pass
        try:
            os.remove(self._stderr_path)
        except OSError:
            pass

    def _verify_capture_output(self) -> None:
        """A failed encoder (e.g. odd frame dimensions) makes ffmpeg exit
        immediately; the capture loop then just sees a broken pipe and
        exits quietly, leaving a 0-byte file that only blows up two
        ffmpeg passes later with an unrelated-looking error. Fail loudly
        and precisely, right here, instead."""
        if os.path.exists(self._raw_path) and os.path.getsize(self._raw_path) > 0:
            return
        raise RuntimeError(
            f"Screen capture produced no video (ffmpeg exit code "
            f"{self._proc.returncode}). ffmpeg reported:\n{self._stderr_tail()}"
        )

    def _retime_to_wall_clock(self, achieved_fps: float) -> None:
        if achieved_fps <= 0:
            return
        scale = float(self._fps) / achieved_fps
        if abs(scale - 1.0) <= _RETIME_TOLERANCE:
            return
        tmp_path = self._raw_path.replace("raw_capture_", "raw_retimed_tmp_")
        try:
            subprocess.run(
                _build_retime_cmd(self._raw_path, tmp_path, scale),
                check=True, capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            os.replace(tmp_path, self._raw_path)
        except (subprocess.CalledProcessError, OSError) as exc:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise RuntimeError(
                f"Could not correct recording timing ({achieved_fps:.1f} fps "
                f"captured vs {self._fps} fps declared). The uncorrected "
                f"capture is still at {self._raw_path}. Cause: {exc}"
            ) from exc

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

        achieved_fps = self._achieved_fps()
        try:
            self._verify_capture_output()
            self._retime_to_wall_clock(achieved_fps)
        finally:
            self._discard_stderr_log()

        if audio_path is not None and os.path.exists(audio_path):
            muxed_tmp = self._raw_path.replace("raw_capture_", "raw_muxed_tmp_")
            try:
                video_duration = _probe_duration(self._raw_path)
                subprocess.run(
                    _build_mux_cmd(self._raw_path, audio_path, muxed_tmp, video_duration),
                    check=True, timeout=60,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                os.replace(muxed_tmp, self._raw_path)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                # Muxing failed (or hung -- see _build_mux_cmd's docstring
                # for the real, previously-hanging apad bug this timeout
                # guards against even if some other edge case reproduces
                # it) -- keep the video-only capture rather than losing
                # the whole recording. Clean up a possibly-still-running
                # or partially-written temp file either way.
                try:
                    os.remove(muxed_tmp)
                except OSError:
                    pass
            finally:
                try:
                    os.remove(audio_path)
                except OSError:
                    pass

        return RecordingSession(
            raw_video_path=self._raw_path,
            cursor_log=cursor_entries,
            rect_left=self._rect["left"],
            rect_top=self._rect["top"],
            rect_width=self._rect["width"],
            rect_height=self._rect["height"],
            fps=achieved_fps,
        )


def start_recording(target: dict, output_dir: str, fps: int = DEFAULT_FPS) -> _ActiveRecording:
    os.makedirs(output_dir, exist_ok=True)
    return _ActiveRecording(target, output_dir, fps)

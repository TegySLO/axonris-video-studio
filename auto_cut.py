"""auto_cut.py -- silence-based auto-cut, reimplementing the DOCUMENTED
APPROACH of WyattBlue/auto-editor (margin/threshold silence-cut model,
verified real/Unlicense/~5k stars/actively maintained) via ffmpeg's own
silencedetect filter -- not a port of auto-editor's Nim code, which
doesn't run in this Python/PySide6 codebase."""
from __future__ import annotations
import re
import subprocess

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

_SILENCE_START_RE = re.compile(r"silence_start:\s*([\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([\d.]+)")


def _probe_duration(path: str) -> float:
    cmd = [FFMPEG, "-i", path]
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", result.stderr)
    if not match:
        # Returning 0.0 here used to make _build_keep_segments truncate the
        # output to just its leading segment, silently discarding most of
        # the recording. Fail loudly instead -- the GUI surfaces this.
        raise RuntimeError(
            f"Could not determine duration of {path} from ffmpeg output. "
            f"ffmpeg reported:\n{result.stderr[-800:].strip()}"
        )
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def _parse_silence_intervals(stderr_text: str) -> list[tuple[float, float]]:
    """Pairs each silence_start with the NEXT silence_end -- ffmpeg emits
    them in order, one pair per detected silent stretch. A trailing
    silence_start with no matching silence_end (recording stopped mid-
    silence) is dropped, not turned into a bogus open-ended interval."""
    starts = [float(m.group(1)) for m in _SILENCE_START_RE.finditer(stderr_text)]
    ends = [float(m.group(1)) for m in _SILENCE_END_RE.finditer(stderr_text)]
    return list(zip(starts, ends))


def _build_keep_segments(total_duration: float, silence_intervals: list[tuple[float, float]], margin_sec: float) -> list[tuple[float, float]]:
    """Same margin model as auto-editor: pad the cut boundary inward by
    margin_sec on each side, so a cut never clips the tail end of speech
    that trails right up against a silent gap. When a silence interval is
    shorter than 2*margin_sec, the two margins would invert (cut_end <
    cut_start), overlapping neighboring keep-segments -- clamp cut_end to
    cut_start so the cut degrades to "cut the whole short silence" instead."""
    if not silence_intervals:
        return [(0.0, total_duration)]
    segments = []
    cursor = 0.0
    for start, end in silence_intervals:
        cut_start = start + margin_sec
        cut_end = max(cut_start, end - margin_sec)
        if cut_start > cursor:
            segments.append((cursor, cut_start))
        cursor = max(cursor, cut_end)
    if cursor < total_duration:
        segments.append((cursor, total_duration))
    return segments


def remove_silence(input_path: str, output_path: str, margin_sec: float = 0.3, noise_threshold_db: int = -30, min_silence_sec: float = 0.5) -> str:
    duration = _probe_duration(input_path)
    detect_cmd = [
        FFMPEG, "-i", input_path,
        "-af", f"silencedetect=noise={noise_threshold_db}dB:d={min_silence_sec}",
        "-f", "null", "-",
    ]
    detect_result = subprocess.run(
        detect_cmd, capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    intervals = _parse_silence_intervals(detect_result.stderr)
    segments = _build_keep_segments(duration, intervals, margin_sec)

    if len(segments) <= 1 and segments == [(0.0, duration)]:
        # Nothing to cut -- still produce a proper libx264-encoded output
        # file at output_path rather than silently leaving input untouched,
        # so callers can always rely on output_path existing afterward.
        cmd = [
            FFMPEG, "-y", "-i", input_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
    else:
        select_expr = "+".join(f"between(t,{s},{e})" for s, e in segments)
        cmd = [
            FFMPEG, "-y", "-i", input_path,
            "-vf", f"select='{select_expr}',setpts=N/FRAME_RATE/TB",
            "-af", f"aselect='{select_expr}',asetpts=N/SR/TB",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            output_path,
        ]

    subprocess.run(cmd, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return output_path

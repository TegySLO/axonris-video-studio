"""tests/test_real_capture.py -- REAL, non-mocked capture tests.

Everything else in this suite mocks subprocess, which is why the branch
could ship green while producing an ~11x-sped-up video with no zoom: no
test ever looked at what ffmpeg actually did. These tests run a genuine
short recording and measure the resulting file with ffmpeg.

They are slow by unit-test standards (a few seconds each) and need a real
display, so they skip cleanly where capture is unavailable (headless CI).
"""
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_cut as ac
import screen_recorder as sr


def _capture_available() -> bool:
    try:
        import mss
        with mss.mss() as sct:
            sct.grab(sct.monitors[1])
        return True
    except Exception:
        return False


CAPTURE_AVAILABLE = _capture_available()


@unittest.skipUnless(CAPTURE_AVAILABLE, "no real display available for screen capture")
class TestRealCaptureTiming(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="axonris_capture_test_")

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_recorded_duration_matches_wall_clock(self):
        """The regression that mocked tests could never catch.

        The capture loop cannot hit an arbitrary requested fps (a 1080p
        grab alone costs ~21 ms), and ffmpeg is told a framerate before
        the achieved rate is known -- so without timestamp correction the
        video plays back sped up and every wall-clock cursor timestamp
        lands outside the video's timeline, meaning no zoom ever fires.
        Measured before the fix: 8.0 s of recording -> 0.68 s of video.
        """
        record_seconds = 3.0
        recording = sr.start_recording(
            {"hwnd": None, "title": "Full screen"}, self._tmpdir,
        )
        started = time.monotonic()
        time.sleep(record_seconds)
        # Measure wall_clock BEFORE calling stop(), not after: stop() does
        # real post-processing work of its own (audio thread join, ffmpeg
        # wait, a retime pass, an audio mux pass) that takes real wall-clock
        # time but has nothing to do with how long the RECORDING itself
        # ran. Including it here would fail this assertion for any short
        # recording purely because teardown overhead is proportionally
        # larger relative to a short clip -- not because the recorded
        # video's own duration is wrong (found live: a 3.0s recording
        # produced 3.00s of video, which is correct, but wall_clock
        # measured after stop() read 4.31s because stop() itself took
        # ~1.3s, making the ratio 0.70 instead of ~1.0).
        wall_clock = time.monotonic() - started
        session = recording.stop()

        self.assertTrue(os.path.exists(session.raw_video_path))
        self.assertGreater(os.path.getsize(session.raw_video_path), 0)

        measured = ac._probe_duration(session.raw_video_path)
        ratio = measured / wall_clock
        self.assertGreater(
            ratio, 0.7,
            f"video is sped up: {measured:.2f}s of video for {wall_clock:.2f}s "
            f"of recording (ratio {ratio:.2f})",
        )
        self.assertLess(
            ratio, 1.3,
            f"video is slowed down: {measured:.2f}s of video for {wall_clock:.2f}s "
            f"of recording (ratio {ratio:.2f})",
        )

    def test_cursor_log_timestamps_fall_inside_the_video_timeline(self):
        """The consequence of the timing bug, asserted directly: zoom
        targets are placed at wall-clock times, so if the video timeline
        is shorter than wall-clock, the zoom windows are unreachable."""
        recording = sr.start_recording(
            {"hwnd": None, "title": "Full screen"}, self._tmpdir,
        )
        time.sleep(2.0)
        session = recording.stop()

        measured = ac._probe_duration(session.raw_video_path)
        self.assertTrue(session.cursor_log, "cursor log should not be empty")
        last_t = session.cursor_log[-1]["t"]
        self.assertLess(
            last_t, measured * 1.3,
            f"last cursor timestamp {last_t:.2f}s is outside a {measured:.2f}s "
            f"video -- zoom targets would never fire",
        )

    def test_session_reports_capture_rect_and_real_fps(self):
        recording = sr.start_recording(
            {"hwnd": None, "title": "Full screen"}, self._tmpdir,
        )
        time.sleep(1.5)
        session = recording.stop()

        self.assertGreater(session.rect_width, 0)
        self.assertGreater(session.rect_height, 0)
        self.assertEqual(session.rect_width % 2, 0)
        self.assertEqual(session.rect_height % 2, 0)
        self.assertGreater(session.fps, 1.0)


@unittest.skipUnless(CAPTURE_AVAILABLE, "no real display available for screen capture")
class TestRealOddDimensionCapture(unittest.TestCase):
    """libx264 + yuv420p aborts on odd frame dimensions, and
    GetWindowRect returns arbitrary sizes -- so before the even-rounding
    fix, recording most real windows killed ffmpeg instantly, the capture
    loop swallowed the broken pipe, and the user got a 0-byte file and a
    permanently dead UI with no error at all."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="axonris_odd_test_")

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    @patch("screen_recorder.win32gui.GetWindowRect")
    def test_odd_sized_window_records_cleanly(self, mock_rect):
        # A real window-target capture whose raw size is 801 x 603.
        mock_rect.return_value = (0, 0, 801, 603)
        recording = sr.start_recording(
            {"hwnd": 12345, "title": "Odd Sized Window"}, self._tmpdir,
        )
        time.sleep(2.0)
        session = recording.stop()

        # Rounded to even, so libx264 accepted it...
        self.assertEqual(session.rect_width, 800)
        self.assertEqual(session.rect_height, 602)
        # ...and it produced a real, non-empty, probe-able video.
        self.assertTrue(os.path.exists(session.raw_video_path))
        self.assertGreater(os.path.getsize(session.raw_video_path), 0)
        self.assertGreater(ac._probe_duration(session.raw_video_path), 0.0)

    def test_a_failed_capture_raises_instead_of_yielding_an_empty_file(self):
        """Whatever else goes wrong with the encoder, stop() must never
        hand back a silent 0-byte file for the next stage to trip over."""
        recording = sr.start_recording(
            {"hwnd": None, "title": "Full screen"}, self._tmpdir,
        )
        time.sleep(0.5)
        # Simulate the encoder having died and left nothing behind.
        recording._stop_event.set()
        recording._thread.join(timeout=5.0)
        recording._proc.kill()
        recording._proc.wait()
        with open(recording._raw_path, "wb"):
            pass  # truncate to 0 bytes

        with self.assertRaises(RuntimeError) as ctx:
            recording.stop()
        self.assertIn("no video", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

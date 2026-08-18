# tests/test_screen_recorder.py
import os
import shutil
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import screen_recorder as sr


class TestResolveCaptureRect(unittest.TestCase):

    @patch("screen_recorder.win32gui.GetWindowRect")
    def test_window_target_uses_window_rect(self, mock_rect):
        mock_rect.return_value = (10, 20, 810, 620)  # left, top, right, bottom
        rect = sr._resolve_capture_rect({"hwnd": 123, "title": "Axonris Forge"})
        self.assertEqual(rect, {"left": 10, "top": 20, "width": 800, "height": 600})

    @patch("screen_recorder.win32gui.GetWindowRect")
    def test_window_target_rounds_odd_dimensions_down_to_even(self, mock_rect):
        # Regression: libx264 + yuv420p aborts with "width not divisible
        # by 2" on odd dimensions, and GetWindowRect returns arbitrary
        # sizes -- so most real windows used to kill ffmpeg instantly.
        mock_rect.return_value = (10, 20, 811, 623)  # 801 x 603
        rect = sr._resolve_capture_rect({"hwnd": 123, "title": "Odd Window"})
        self.assertEqual(rect["width"] % 2, 0)
        self.assertEqual(rect["height"] % 2, 0)
        self.assertEqual(rect, {"left": 10, "top": 20, "width": 800, "height": 602})

    @patch("screen_recorder.mss.mss")
    def test_full_screen_target_uses_primary_monitor(self, mock_mss_cls):
        mock_sct = MagicMock()
        mock_sct.monitors = [
            {"left": 0, "top": 0, "width": 1920, "height": 1080},  # index 0 = "all monitors"
            {"left": 0, "top": 0, "width": 1920, "height": 1080},  # index 1 = primary
        ]
        mock_mss_cls.return_value.__enter__.return_value = mock_sct
        rect = sr._resolve_capture_rect({"hwnd": None, "title": "Full screen"})
        self.assertEqual(rect, {"left": 0, "top": 0, "width": 1920, "height": 1080})

    @patch("screen_recorder.mss.mss")
    def test_full_screen_target_also_rounds_to_even(self, mock_mss_cls):
        mock_sct = MagicMock()
        mock_sct.monitors = [
            {"left": 0, "top": 0, "width": 1365, "height": 767},
            {"left": 0, "top": 0, "width": 1365, "height": 767},
        ]
        mock_mss_cls.return_value.__enter__.return_value = mock_sct
        rect = sr._resolve_capture_rect({"hwnd": None, "title": "Full screen"})
        self.assertEqual((rect["width"], rect["height"]), (1364, 766))


class TestFfmpegCommandConstruction(unittest.TestCase):

    def test_never_uses_gpu_encoding(self):
        cmd = sr._build_ffmpeg_capture_cmd(
            rect={"left": 0, "top": 0, "width": 800, "height": 600},
            fps=30, output_path="C:/tmp/out.mp4",
        )
        joined = " ".join(cmd)
        self.assertIn("libx264", joined)
        for banned in ("h264_amf", "nvenc", "cuda"):
            self.assertNotIn(banned, joined.lower())

    def test_uses_create_no_window_when_spawned(self):
        with patch("screen_recorder.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            sr._spawn_ffmpeg_capture(
                rect={"left": 0, "top": 0, "width": 800, "height": 600},
                fps=30, output_path="C:/tmp/out.mp4",
            )
            _, kwargs = mock_popen.call_args
            self.assertEqual(kwargs.get("creationflags"), getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _fake_recording(raw_path, audio_path=None, frames=150, elapsed=10.0):
    """Builds an _ActiveRecording with its collaborators mocked out, so
    stop()'s post-capture sequence can be tested without a real capture.
    frames/elapsed control the achieved-fps calculation."""
    recording = sr._ActiveRecording.__new__(sr._ActiveRecording)
    recording._stop_event = MagicMock()
    recording._thread = MagicMock()
    recording._cursor_logger = MagicMock()
    recording._cursor_logger.stop.return_value = []
    recording._audio_capture = MagicMock()
    recording._audio_capture.stop.return_value = audio_path
    recording._raw_path = raw_path
    recording._rect = {"left": 10, "top": 20, "width": 800, "height": 600}
    recording._fps = 15
    recording._frame_count = frames
    recording._capture_started_at = 0.0
    recording._capture_ended_at = elapsed
    recording._stderr_file = MagicMock()
    recording._stderr_path = raw_path + ".log"
    recording._proc = MagicMock()
    recording._proc.returncode = 0
    recording._proc.wait.return_value = None
    return recording


class TestActiveRecordingStop(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.raw_path = os.path.join(self._tmpdir, "raw_capture_1.mp4")
        with open(self.raw_path, "wb") as f:
            f.write(b"not-really-an-mp4-but-non-empty")

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    @patch("screen_recorder.subprocess.run")
    def test_stop_kills_process_on_wait_timeout(self, mock_run):
        recording = _fake_recording(self.raw_path)
        recording._proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="ffmpeg", timeout=10), None,
        ]

        session = recording.stop()

        recording._proc.kill.assert_called_once()
        self.assertEqual(recording._proc.wait.call_count, 2)
        self.assertEqual(session.raw_video_path, self.raw_path)

    def test_stop_raises_when_capture_produced_an_empty_file(self):
        # Regression: an odd-dimension window killed ffmpeg instantly, the
        # capture loop swallowed the broken pipe, and stop() happily
        # returned a session pointing at a 0-byte file -- which then blew
        # up two ffmpeg passes later with an unrelated-looking error and a
        # permanently dead UI. It must fail here, loudly.
        empty_path = os.path.join(self._tmpdir, "raw_capture_empty.mp4")
        open(empty_path, "wb").close()
        recording = _fake_recording(empty_path)
        recording._proc.returncode = 1

        with self.assertRaises(RuntimeError) as ctx:
            recording.stop()
        self.assertIn("no video", str(ctx.exception))

    @patch("screen_recorder.os.replace")
    @patch("screen_recorder.subprocess.run")
    def test_stop_retimes_capture_to_wall_clock(self, mock_run, mock_replace):
        # 150 frames over 10 s = 15 fps achieved against 15 declared ->
        # no correction. 75 frames over 10 s = 7.5 fps achieved -> the
        # file claims 15 fps, so timestamps must be scaled by 2.0.
        recording = _fake_recording(self.raw_path, frames=75, elapsed=10.0)
        session = recording.stop()

        retime_cmd = mock_run.call_args_list[0][0][0]
        self.assertIn("-itsscale", retime_cmd)
        scale = float(retime_cmd[retime_cmd.index("-itsscale") + 1])
        self.assertAlmostEqual(scale, 2.0, places=3)
        self.assertIn("copy", retime_cmd)
        self.assertAlmostEqual(session.fps, 7.5, places=3)

    @patch("screen_recorder.subprocess.run")
    def test_stop_skips_retime_when_achieved_fps_matches(self, mock_run):
        recording = _fake_recording(self.raw_path, frames=150, elapsed=10.0)
        recording.stop()
        self.assertEqual(mock_run.call_count, 0)

    def test_session_carries_capture_rect_and_achieved_fps(self):
        with patch("screen_recorder.subprocess.run"), patch("screen_recorder.os.replace"):
            session = _fake_recording(self.raw_path, frames=120, elapsed=10.0).stop()
        self.assertEqual((session.rect_left, session.rect_top), (10, 20))
        self.assertEqual((session.rect_width, session.rect_height), (800, 600))
        self.assertAlmostEqual(session.fps, 12.0, places=3)

    @patch("screen_recorder._probe_duration", return_value=5.0)
    @patch("screen_recorder.os.replace")
    @patch("screen_recorder.os.remove")
    @patch("screen_recorder.subprocess.run")
    def test_stop_muxes_audio_into_raw_path_when_audio_capture_succeeds(
        self, mock_run, mock_remove, mock_replace, mock_probe,
    ):
        # _probe_duration is mocked here (rather than allowed to run for
        # real) because stop() now calls it to bound apad's duration before
        # building the mux command -- letting it hit a real ffmpeg process
        # against this test's fake paths would defeat the point of this
        # test being fully mocked, and (since a real probe on a
        # nonexistent path now raises, per the sibling fix for silent
        # duration-probe failures) would make the test fail for an
        # unrelated reason.
        audio_path = os.path.join(self._tmpdir, "raw_audio_1.wav")
        open(audio_path, "wb").close()
        recording = _fake_recording(self.raw_path, audio_path=audio_path)

        session = recording.stop()

        mux_cmd = mock_run.call_args_list[-1][0][0]
        joined = " ".join(mux_cmd)
        self.assertIn("-c:a", mux_cmd)
        self.assertIn("aac", mux_cmd)
        self.assertNotIn("h264_amf", joined.lower())
        self.assertNotIn("nvenc", joined.lower())
        # Muxed temp file replaces the video-only capture at the original path
        mock_replace.assert_called_once()
        self.assertEqual(mock_replace.call_args[0][1], self.raw_path)
        # (the ffmpeg stderr log is also cleaned up, hence not assert_called_once)
        self.assertIn(audio_path, [c[0][0] for c in mock_remove.call_args_list])
        self.assertEqual(session.raw_video_path, self.raw_path)

    def test_mux_pads_audio_so_a_short_audio_track_cannot_truncate_video(self):
        # Regression, and the single most destructive bug in this branch:
        # WASAPI loopback yields NO samples while nothing is playing, so a
        # silent 8 s tutorial capture produced ~1.3 s of audio -- and a
        # bare -shortest then truncated the VIDEO to 1.3 s, throwing away
        # ~85% of the recording. apad pads the audio to the video length
        # first, so -shortest can only ever trim the padding.
        cmd = sr._build_mux_cmd("v.mp4", "a.wav", "out.mp4", video_duration=12.5)
        joined = " ".join(cmd)
        self.assertIn("apad", joined)
        # apad must carry an explicit, finite bound (whole_dur=<duration>) --
        # an unbounded apad[a] made ffmpeg hang indefinitely in real testing
        # (4 separate live mux runs never terminated on their own), because
        # -shortest alone did not reliably stop an infinite-duration audio
        # generator in this filter_complex shape.
        self.assertIn("apad=whole_dur=12.500000", joined)
        self.assertIn("-map", cmd)
        self.assertIn("0:v:0", cmd)
        # video is still copied, never re-encoded (no GPU-encoding risk)
        self.assertIn("copy", cmd)
        for banned in ("h264_amf", "nvenc", "cuda"):
            self.assertNotIn(banned, joined.lower())

    @patch("screen_recorder.subprocess.run")
    def test_stop_skips_mux_when_audio_capture_fails(self, mock_run):
        recording = _fake_recording(self.raw_path, audio_path=None)
        session = recording.stop()
        # only the retime pass may have run; no mux command
        for call in mock_run.call_args_list:
            self.assertNotIn("apad", " ".join(call[0][0]))
        self.assertEqual(session.raw_video_path, self.raw_path)


class TestAudioCapture(unittest.TestCase):

    @patch("screen_recorder.wave.open")
    @patch("screen_recorder.pyaudio.PyAudio")
    def test_start_opens_wasapi_loopback_stream_and_stop_returns_wav_path(self, mock_pyaudio_cls, mock_wave_open):
        mock_pa = MagicMock()
        mock_pyaudio_cls.return_value = mock_pa
        mock_pa.get_default_wasapi_loopback.return_value = {
            "index": 20, "name": "Speakers [Loopback]",
            "maxInputChannels": 2, "defaultSampleRate": 48000.0,
            "isLoopbackDevice": True,
        }
        mock_stream = MagicMock()
        mock_stream.read.return_value = b"\x00\x00" * 1024
        mock_pa.open.return_value = mock_stream

        capture = sr.AudioCapture()
        capture.start("C:/tmp", 12345)
        _, open_kwargs = mock_pa.open.call_args
        self.assertEqual(open_kwargs["channels"], 2)
        self.assertEqual(open_kwargs["rate"], 48000)
        self.assertEqual(open_kwargs["input_device_index"], 20)

        result = capture.stop()
        self.assertEqual(result, os.path.join("C:/tmp", "raw_audio_12345.wav"))
        mock_stream.close.assert_called_once()
        mock_pa.terminate.assert_called_once()

    @patch("screen_recorder.pyaudio.PyAudio")
    def test_start_fails_soft_when_no_loopback_device(self, mock_pyaudio_cls):
        mock_pa = MagicMock()
        mock_pyaudio_cls.return_value = mock_pa
        mock_pa.get_default_wasapi_loopback.side_effect = OSError("no default output device")

        capture = sr.AudioCapture()
        capture.start("C:/tmp", 12345)
        result = capture.stop()
        self.assertIsNone(result)
        # The soft failure must record WHY -- otherwise a real setup bug
        # is indistinguishable from "this machine has no loopback device".
        self.assertIsNotNone(capture.last_error)
        self.assertIn("no default output device", capture.last_error)


if __name__ == "__main__":
    unittest.main()

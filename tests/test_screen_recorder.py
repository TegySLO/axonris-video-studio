# tests/test_screen_recorder.py
import os
import sys
import subprocess
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


class TestActiveRecordingStop(unittest.TestCase):

    def test_stop_kills_process_on_wait_timeout(self):
        recording = sr._ActiveRecording.__new__(sr._ActiveRecording)
        recording._stop_event = MagicMock()
        recording._thread = MagicMock()
        recording._cursor_logger = MagicMock()
        recording._cursor_logger.stop.return_value = []
        recording._audio_capture = MagicMock()
        recording._audio_capture.stop.return_value = None
        recording._raw_path = "C:/tmp/out.mp4"
        recording._proc = MagicMock()
        recording._proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="ffmpeg", timeout=10), None]

        session = recording.stop()

        recording._proc.kill.assert_called_once()
        self.assertEqual(recording._proc.wait.call_count, 2)
        self.assertEqual(session.raw_video_path, "C:/tmp/out.mp4")

    @patch("screen_recorder.os.path.exists")
    @patch("screen_recorder.os.replace")
    @patch("screen_recorder.os.remove")
    @patch("screen_recorder.subprocess.run")
    def test_stop_muxes_audio_into_raw_path_when_audio_capture_succeeds(
        self, mock_run, mock_remove, mock_replace, mock_exists,
    ):
        mock_exists.return_value = True
        recording = sr._ActiveRecording.__new__(sr._ActiveRecording)
        recording._stop_event = MagicMock()
        recording._thread = MagicMock()
        recording._cursor_logger = MagicMock()
        recording._cursor_logger.stop.return_value = []
        recording._audio_capture = MagicMock()
        recording._audio_capture.stop.return_value = "C:/tmp/raw_audio_1.wav"
        recording._raw_path = "C:/tmp/raw_capture_1.mp4"
        recording._proc = MagicMock()
        recording._proc.wait.return_value = None

        session = recording.stop()

        mock_run.assert_called_once()
        mux_cmd = mock_run.call_args[0][0]
        joined = " ".join(mux_cmd)
        self.assertIn("-c:a", mux_cmd)
        self.assertIn("aac", mux_cmd)
        self.assertNotIn("h264_amf", joined.lower())
        self.assertNotIn("nvenc", joined.lower())
        # Muxed temp file replaces the video-only capture at the original path
        mock_replace.assert_called_once()
        replace_args = mock_replace.call_args[0]
        self.assertEqual(replace_args[1], "C:/tmp/raw_capture_1.mp4")
        mock_remove.assert_called_once_with("C:/tmp/raw_audio_1.wav")
        self.assertEqual(session.raw_video_path, "C:/tmp/raw_capture_1.mp4")

    @patch("screen_recorder.subprocess.run")
    def test_stop_skips_mux_when_audio_capture_fails(self, mock_run):
        recording = sr._ActiveRecording.__new__(sr._ActiveRecording)
        recording._stop_event = MagicMock()
        recording._thread = MagicMock()
        recording._cursor_logger = MagicMock()
        recording._cursor_logger.stop.return_value = []
        recording._audio_capture = MagicMock()
        recording._audio_capture.stop.return_value = None
        recording._raw_path = "C:/tmp/raw_capture_1.mp4"
        recording._proc = MagicMock()
        recording._proc.wait.return_value = None

        session = recording.stop()

        mock_run.assert_not_called()
        self.assertEqual(session.raw_video_path, "C:/tmp/raw_capture_1.mp4")


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


if __name__ == "__main__":
    unittest.main()

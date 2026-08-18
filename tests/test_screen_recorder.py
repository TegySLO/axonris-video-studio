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


if __name__ == "__main__":
    unittest.main()

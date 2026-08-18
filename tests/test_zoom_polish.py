import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zoom_polish as zp
from screen_recorder import RecordingSession


class TestFindZoomTargets(unittest.TestCase):

    def test_finds_click_clusters_as_zoom_targets(self):
        cursor_log = [
            {"t": 0.0, "x": 100, "y": 100, "click": False},
            {"t": 1.0, "x": 500, "y": 300, "click": True},
            {"t": 1.1, "x": 500, "y": 300, "click": True},
            {"t": 4.0, "x": 900, "y": 700, "click": True},
        ]
        targets = zp.find_zoom_targets(cursor_log)
        # two distinct click clusters -> two zoom targets, deduplicated
        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0]["x"], 500)
        self.assertEqual(targets[0]["y"], 300)
        self.assertAlmostEqual(targets[0]["t"], 1.0, delta=0.2)
        self.assertEqual(targets[1]["x"], 900)

    def test_no_clicks_means_no_zoom_targets(self):
        cursor_log = [{"t": 0.0, "x": 100, "y": 100, "click": False}]
        self.assertEqual(zp.find_zoom_targets(cursor_log), [])


class TestZoomStyleToScale(unittest.TestCase):

    def test_moderate_and_aggressive_produce_different_scale(self):
        moderate = zp._zoom_scale_for_style("moderate")
        aggressive = zp._zoom_scale_for_style("aggressive")
        self.assertGreater(aggressive, moderate)
        self.assertGreater(moderate, 1.0)  # any zoom style actually zooms IN


class TestApplyZoom(unittest.TestCase):

    @patch("zoom_polish.subprocess.run")
    def test_builds_ffmpeg_filter_and_calls_libx264(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        session = RecordingSession(raw_video_path="C:/tmp/raw.mp4", cursor_log=[
            {"t": 1.0, "x": 500, "y": 300, "click": True},
        ])
        result = zp.apply_zoom(session, "C:/tmp/zoomed.mp4", style="moderate")
        self.assertEqual(result, "C:/tmp/zoomed.mp4")
        cmd = mock_run.call_args[0][0]
        joined = " ".join(cmd)
        self.assertIn("libx264", joined)
        self.assertNotIn("h264_amf", joined.lower())

    @patch("zoom_polish.subprocess.run")
    def test_no_click_targets_still_produces_output_unzoomed(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        session = RecordingSession(raw_video_path="C:/tmp/raw.mp4", cursor_log=[])
        result = zp.apply_zoom(session, "C:/tmp/zoomed.mp4")
        self.assertEqual(result, "C:/tmp/zoomed.mp4")
        mock_run.assert_called_once()

    @patch("zoom_polish.subprocess.run")
    def test_filter_uses_time_variable_and_real_click_coordinates(self, mock_run):
        # Regression: zoompan's seconds-based variable is `time`, not a
        # bare `t` (which isn't defined for this filter and would fail
        # ffmpeg filter init against a real binary). And the zoom must
        # actually center on the click's x/y, not default to 0,0.
        mock_run.return_value = MagicMock(returncode=0)
        session = RecordingSession(
            raw_video_path="C:/tmp/raw.mp4",
            cursor_log=[{"t": 1.0, "x": 500, "y": 300, "click": True}],
            rect_width=1920, rect_height=1080, fps=15.0,
        )
        zp.apply_zoom(session, "C:/tmp/zoomed.mp4", style="moderate")
        cmd = mock_run.call_args[0][0]
        filter_arg = cmd[cmd.index("-vf") + 1]
        # Must reference zoompan's `time` variable, not a bare `t` (guard
        # against a stray "between(t," substring collision with "time").
        self.assertIn("between(time,", filter_arg)
        self.assertNotIn("between(t,", filter_arg)
        # The click's actual x/y must appear in the x/y expressions.
        self.assertIn("500", filter_arg)
        self.assertIn("300", filter_arg)

    @patch("zoom_polish.subprocess.run")
    def test_click_coordinates_are_translated_into_frame_space(self, mock_run):
        # Regression: cursor_log stores SCREEN-absolute coordinates
        # (win32api.GetCursorPos), but zoompan's x/y are relative to the
        # captured frame's origin. Recording a window at (300, 200) used
        # to aim the zoom 300px right and 200px down of the real click.
        mock_run.return_value = MagicMock(returncode=0)
        session = RecordingSession(
            raw_video_path="C:/tmp/raw.mp4",
            cursor_log=[{"t": 1.0, "x": 500, "y": 300, "click": True}],
            rect_left=300, rect_top=200, rect_width=800, rect_height=600, fps=15.0,
        )
        zp.apply_zoom(session, "C:/tmp/zoomed.mp4")
        filter_arg = mock_run.call_args[0][0][
            mock_run.call_args[0][0].index("-vf") + 1
        ]
        # 500-300 = 200 across, 300-200 = 100 down
        self.assertIn("200-(iw/zoom/2)", filter_arg)
        self.assertIn("100-(ih/zoom/2)", filter_arg)
        # and NOT the untranslated screen coordinates
        self.assertNotIn("500-(iw/zoom/2)", filter_arg)
        self.assertNotIn("300-(ih/zoom/2)", filter_arg)

    @patch("zoom_polish.subprocess.run")
    def test_filter_preserves_source_fps_and_size(self, mock_run):
        # Regression: zoompan defaults to fps=25 and s=hd720, so leaving
        # them unset silently retimed every capture to 25 fps, and the
        # old hardcoded s=hd1080 stretched every non-1080p window.
        mock_run.return_value = MagicMock(returncode=0)
        session = RecordingSession(
            raw_video_path="C:/tmp/raw.mp4",
            cursor_log=[{"t": 1.0, "x": 400, "y": 300, "click": True}],
            rect_width=1280, rect_height=800, fps=15.0,
        )
        zp.apply_zoom(session, "C:/tmp/zoomed.mp4")
        filter_arg = mock_run.call_args[0][0][
            mock_run.call_args[0][0].index("-vf") + 1
        ]
        self.assertIn("s=1280x800", filter_arg)
        self.assertIn("fps=15", filter_arg)
        self.assertNotIn("hd1080", filter_arg)

    @patch("zoom_polish.subprocess.run")
    def test_odd_capture_size_is_rounded_even_for_libx264(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        session = RecordingSession(
            raw_video_path="C:/tmp/raw.mp4",
            cursor_log=[{"t": 1.0, "x": 10, "y": 10, "click": True}],
            rect_width=801, rect_height=603, fps=15.0,
        )
        zp.apply_zoom(session, "C:/tmp/zoomed.mp4")
        filter_arg = mock_run.call_args[0][0][
            mock_run.call_args[0][0].index("-vf") + 1
        ]
        self.assertIn("s=800x602", filter_arg)

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
        session = RecordingSession(raw_video_path="C:/tmp/raw.mp4", cursor_log=[
            {"t": 1.0, "x": 500, "y": 300, "click": True},
        ])
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

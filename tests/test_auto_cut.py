import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_cut as ac


class TestParseSilenceIntervals(unittest.TestCase):

    def test_parses_silencedetect_stderr_output(self):
        # Real ffmpeg silencedetect output shape (stderr lines), not invented.
        stderr_text = (
            "[silencedetect @ 0x1] silence_start: 2.5\n"
            "[silencedetect @ 0x1] silence_end: 4.1 | silence_duration: 1.6\n"
            "[silencedetect @ 0x1] silence_start: 10.0\n"
            "[silencedetect @ 0x1] silence_end: 11.0 | silence_duration: 1.0\n"
        )
        intervals = ac._parse_silence_intervals(stderr_text)
        self.assertEqual(intervals, [(2.5, 4.1), (10.0, 11.0)])

    def test_ignores_unmatched_start_at_end_of_stream(self):
        # A silence_start with no matching silence_end (recording stopped
        # mid-silence) must not crash the parser or produce a bogus interval.
        stderr_text = "[silencedetect @ 0x1] silence_start: 30.0\n"
        intervals = ac._parse_silence_intervals(stderr_text)
        self.assertEqual(intervals, [])


class TestBuildKeepSegments(unittest.TestCase):

    def test_silence_in_the_middle_produces_two_keep_segments(self):
        segments = ac._build_keep_segments(
            total_duration=20.0, silence_intervals=[(8.0, 12.0)], margin_sec=0.3,
        )
        # keep 0 -> 8.3 (silence start + margin) and 11.7 -> 20 (silence end - margin)
        self.assertEqual(len(segments), 2)
        self.assertAlmostEqual(segments[0][0], 0.0)
        self.assertAlmostEqual(segments[0][1], 8.3)
        self.assertAlmostEqual(segments[1][0], 11.7)
        self.assertAlmostEqual(segments[1][1], 20.0)

    def test_no_silence_means_one_full_segment(self):
        segments = ac._build_keep_segments(total_duration=20.0, silence_intervals=[], margin_sec=0.3)
        self.assertEqual(segments, [(0.0, 20.0)])


class TestRemoveSilence(unittest.TestCase):

    @patch("auto_cut.subprocess.run")
    @patch("auto_cut._probe_duration")
    def test_calls_ffmpeg_with_libx264_only(self, mock_duration, mock_run):
        mock_duration.return_value = 20.0
        mock_run.side_effect = [
            MagicMock(returncode=0, stderr=""),  # silencedetect pass
            MagicMock(returncode=0),              # final encode pass
        ]
        result = ac.remove_silence("C:/tmp/in.mp4", "C:/tmp/out.mp4")
        self.assertEqual(result, "C:/tmp/out.mp4")
        final_cmd = mock_run.call_args_list[-1][0][0]
        joined = " ".join(final_cmd)
        self.assertIn("libx264", joined)
        self.assertNotIn("h264_amf", joined.lower())

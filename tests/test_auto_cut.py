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

    def test_short_silence_below_double_margin_does_not_invert_or_overlap(self):
        # Regression: a silence shorter than 2*margin_sec (here 0.4s < 0.6s)
        # used to make cut_end < cut_start, producing overlapping
        # keep-segments around consecutive short silences.
        segments = ac._build_keep_segments(
            total_duration=20.0,
            silence_intervals=[(10.0, 10.4), (15.0, 15.4)],
            margin_sec=0.3,
        )
        for prev, cur in zip(segments, segments[1:]):
            self.assertLessEqual(prev[1], cur[0])
        for start, end in segments:
            self.assertLessEqual(start, end)


class TestProbeDuration(unittest.TestCase):

    @patch("auto_cut.subprocess.run")
    def test_raises_when_duration_cannot_be_parsed(self, mock_run):
        # Regression: returning 0.0 here made _build_keep_segments
        # truncate the output to its leading segment, silently discarding
        # most of the recording. It must surface as a real error instead.
        mock_run.return_value = MagicMock(returncode=1, stderr="moov atom not found\n")
        with self.assertRaises(RuntimeError) as ctx:
            ac._probe_duration("C:/tmp/broken.mp4")
        self.assertIn("Could not determine duration", str(ctx.exception))

    @patch("auto_cut.subprocess.run")
    def test_parses_hh_mm_ss(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stderr="  Duration: 00:01:30.50, start: 0.000000\n",
        )
        self.assertAlmostEqual(ac._probe_duration("C:/tmp/ok.mp4"), 90.5, places=2)


class TestKeptDuration(unittest.TestCase):

    def test_sums_segment_durations(self):
        self.assertAlmostEqual(ac._kept_duration([(0.0, 5.0), (10.0, 12.0)]), 7.0)

    def test_empty_segments_is_zero(self):
        self.assertEqual(ac._kept_duration([]), 0.0)


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

    @patch("auto_cut.subprocess.run")
    @patch("auto_cut._probe_duration")
    def test_all_silent_track_is_not_destroyed(self, mock_duration, mock_run):
        # Regression, found by a full real end-to-end run (record -> zoom
        # -> auto-cut): WASAPI loopback captures SYSTEM audio output, not
        # the microphone -- a normal tutorial (narration via mic, nothing
        # playing through speakers) yields a fully-silent loopback track.
        # silencedetect correctly reports the whole track as one silence
        # interval, and without a guard this "correctly" cut a real 5.07s
        # recording down to 0.62s (just the two margin slivers) -- 88% of
        # the recording destroyed. A single "silence" spanning nearly the
        # whole 20s track (18s out of 20s) should be treated as "this
        # isn't normal speech-with-pauses" and skip the cut, not applied.
        mock_duration.return_value = 20.0
        mock_run.side_effect = [
            MagicMock(
                returncode=0,
                stderr=(
                    "[silencedetect @ 0x1] silence_start: 1.0\n"
                    "[silencedetect @ 0x1] silence_end: 19.0 | silence_duration: 18.0\n"
                ),
            ),
            MagicMock(returncode=0),  # passthrough encode pass
        ]
        ac.remove_silence("C:/tmp/in.mp4", "C:/tmp/out.mp4", min_keep_ratio=0.3)
        final_cmd = mock_run.call_args_list[-1][0][0]
        joined = " ".join(final_cmd)
        # Passthrough branch has no -vf select/aselect filter -- if a cut
        # were (wrongly) still applied, "select=" would appear here.
        self.assertNotIn("select=", joined)

    @patch("auto_cut.subprocess.run")
    @patch("auto_cut._probe_duration")
    def test_genuine_pauses_still_get_cut(self, mock_duration, mock_run):
        # The guard must not disable cutting altogether -- normal speech
        # with real pauses (well under the min_keep_ratio threshold of
        # content lost) should still be cut as before.
        mock_duration.return_value = 20.0
        mock_run.side_effect = [
            MagicMock(
                returncode=0,
                stderr=(
                    "[silencedetect @ 0x1] silence_start: 8.0\n"
                    "[silencedetect @ 0x1] silence_end: 12.0 | silence_duration: 4.0\n"
                ),
            ),
            MagicMock(returncode=0),
        ]
        ac.remove_silence("C:/tmp/in.mp4", "C:/tmp/out.mp4", min_keep_ratio=0.3)
        final_cmd = mock_run.call_args_list[-1][0][0]
        joined = " ".join(final_cmd)
        self.assertIn("select=", joined)

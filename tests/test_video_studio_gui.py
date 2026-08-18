import os
import sys
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

import video_studio_gui as vsg


class TestVideoStudioWindow(unittest.TestCase):

    def test_starts_on_home_page(self):
        win = vsg.VideoStudioWindow()
        self.assertIs(win._stack.currentWidget(), win._page_home)

    def test_generate_button_navigates_to_generate_page(self):
        win = vsg.VideoStudioWindow()
        win._btn_generate.click()
        self.assertIs(win._stack.currentWidget(), win._page_generate)

    def test_record_button_navigates_to_record_page(self):
        win = vsg.VideoStudioWindow()
        win._btn_record.click()
        self.assertIs(win._stack.currentWidget(), win._page_record)

    def test_back_button_returns_to_home_from_generate(self):
        win = vsg.VideoStudioWindow()
        win._btn_generate.click()
        win._page_generate._btn_back.click()
        self.assertIs(win._stack.currentWidget(), win._page_home)

    def test_back_button_returns_to_home_from_record(self):
        win = vsg.VideoStudioWindow()
        win._btn_record.click()
        win._page_record._btn_back.click()
        self.assertIs(win._stack.currentWidget(), win._page_home)


class TestRecordPageWiring(unittest.TestCase):

    def setUp(self):
        self.win = vsg.VideoStudioWindow()
        self.win._btn_record.click()
        self.page = self.win._page_record

    def test_window_picker_populated_on_page_show(self):
        with unittest.mock.patch("video_studio_gui.list_recordable_windows") as mock_list:
            mock_list.return_value = [
                {"hwnd": None, "title": "Full screen"},
                {"hwnd": 111, "title": "Axonris Forge"},
            ]
            self.page.refresh_window_list()
            titles = [self.page._window_combo.itemText(i) for i in range(self.page._window_combo.count())]
            self.assertIn("Full screen", titles)
            self.assertIn("Axonris Forge", titles)

    def test_start_button_disabled_until_window_selected(self):
        self.page._window_combo.clear()
        self.page._on_selection_changed()
        self.assertFalse(self.page._btn_start.isEnabled())

    def test_start_recording_calls_screen_recorder(self):
        self.page._window_combo.clear()
        self.page._window_combo.addItem("Full screen", {"hwnd": None, "title": "Full screen"})
        self.page._on_selection_changed()
        # QFileDialog.getExistingDirectory is a real native (non-Qt-drawn)
        # Windows dialog -- it blocks waiting for a live user even under
        # pytest, so it must be mocked here too, not just start_recording,
        # or this test hangs forever on a machine with a real display
        # (found by running this exact test unmocked -- it hung).
        with unittest.mock.patch("video_studio_gui.QFileDialog.getExistingDirectory", return_value="C:/fake_output_dir"), \
             unittest.mock.patch("video_studio_gui.start_recording") as mock_start:
            mock_session = unittest.mock.MagicMock()
            mock_start.return_value = mock_session
            self.page._btn_start.click()
            mock_start.assert_called_once()
            self.assertEqual(self.page._active_recording, mock_session)
            self.assertTrue(self.page._btn_stop.isEnabled())
            self.assertFalse(self.page._btn_start.isEnabled())


class TestPostProcessWorker(unittest.TestCase):
    """The worker runs the ffmpeg passes off the GUI thread. These call
    run() directly (synchronously) -- the point is the logic inside it,
    not Qt's threading, which is exercised by the real live check."""

    def _worker(self, recording, output_dir="C:/out"):
        return vsg._PostProcessWorker(recording, output_dir)

    def test_success_emits_final_path(self):
        recording = unittest.mock.MagicMock()
        recording.stop.return_value = unittest.mock.MagicMock(
            raw_video_path="C:/out/raw_capture_42.mp4",
        )
        worker = self._worker(recording)
        seen = []
        worker.result_signal.connect(lambda ok, msg: seen.append((ok, msg)))
        with unittest.mock.patch("video_studio_gui.apply_zoom") as mock_zoom, \
                unittest.mock.patch("video_studio_gui.remove_silence") as mock_cut:
            worker.run()
        self.assertEqual(len(seen), 1)
        ok, msg = seen[0]
        self.assertTrue(ok)
        self.assertTrue(msg.endswith("final_42.mp4"), msg)
        # zoom writes zoomed_*, cut reads zoomed_* and writes final_*
        self.assertTrue(mock_zoom.call_args[0][1].endswith("zoomed_42.mp4"))
        self.assertTrue(mock_cut.call_args[0][0].endswith("zoomed_42.mp4"))

    def test_failure_is_reported_instead_of_escaping(self):
        # Regression: an ffmpeg failure used to escape the clicked-slot,
        # leaving BOTH buttons disabled and the status stuck on
        # "Processing..." -- a dead page until the app was restarted.
        recording = unittest.mock.MagicMock()
        recording.stop.side_effect = RuntimeError("Screen capture produced no video")
        worker = self._worker(recording)
        seen = []
        worker.result_signal.connect(lambda ok, msg: seen.append((ok, msg)))
        worker.run()
        self.assertEqual(len(seen), 1)
        ok, msg = seen[0]
        self.assertFalse(ok)
        self.assertIn("Screen capture produced no video", msg)

    def test_output_dir_containing_marker_substring_is_not_corrupted(self):
        # Regression: whole-path str.replace() also rewrote the DIRECTORY
        # component when the chosen folder contained "raw_capture_".
        recording = unittest.mock.MagicMock()
        outdir = os.path.join("C:/", "raw_capture_videos")
        recording.stop.return_value = unittest.mock.MagicMock(
            raw_video_path=os.path.join(outdir, "raw_capture_7.mp4"),
        )
        worker = self._worker(recording, output_dir=outdir)
        seen = []
        worker.result_signal.connect(lambda ok, msg: seen.append((ok, msg)))
        with unittest.mock.patch("video_studio_gui.apply_zoom"), \
                unittest.mock.patch("video_studio_gui.remove_silence"):
            worker.run()
        ok, msg = seen[0]
        self.assertTrue(ok)
        # the directory must survive intact
        self.assertIn("raw_capture_videos", msg)
        self.assertTrue(os.path.basename(msg) == "final_7.mp4", msg)


class TestRecordPageErrorHandling(unittest.TestCase):

    def setUp(self):
        self.win = vsg.VideoStudioWindow()
        self.win._btn_record.click()
        self.page = self.win._page_record

    def test_failed_processing_reenables_start_and_shows_error(self):
        self.page._window_combo.clear()
        self.page._window_combo.addItem("Full screen", {"hwnd": None, "title": "Full screen"})
        self.page._on_processing_finished(False, "RuntimeError: ffmpeg exploded")
        self.assertIn("Failed", self.page._status_lbl.text())
        self.assertIn("ffmpeg exploded", self.page._status_lbl.text())
        self.assertTrue(self.page._btn_start.isEnabled())

    def test_successful_processing_shows_final_path(self):
        self.page._window_combo.clear()
        self.page._window_combo.addItem("Full screen", {"hwnd": None, "title": "Full screen"})
        self.page._on_processing_finished(True, "C:/out/final_1.mp4")
        self.assertIn("final_1.mp4", self.page._status_lbl.text())
        self.assertTrue(self.page._btn_start.isEnabled())

    def test_shutdown_stops_an_active_recording(self):
        recording = unittest.mock.MagicMock()
        self.page._active_recording = recording
        self.page.shutdown()
        recording.stop.assert_called_once()
        self.assertIsNone(self.page._active_recording)

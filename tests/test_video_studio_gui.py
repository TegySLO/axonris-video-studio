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

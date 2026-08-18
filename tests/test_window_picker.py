import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import window_picker as wp


class TestListRecordableWindows(unittest.TestCase):

    @patch("window_picker.win32process.GetWindowThreadProcessId")
    @patch("window_picker.win32gui.GetWindowText")
    @patch("window_picker.win32gui.IsWindowVisible")
    @patch("window_picker.win32gui.EnumWindows")
    @patch("window_picker.os.getpid")
    def test_full_screen_entry_always_first(self, mock_getpid, mock_enum, mock_visible, mock_text, mock_pid):
        mock_getpid.return_value = 999
        mock_enum.side_effect = lambda cb, _: None  # no windows found
        result = wp.list_recordable_windows()
        self.assertEqual(result[0], {"hwnd": None, "title": "Full screen"})

    @patch("window_picker.win32process.GetWindowThreadProcessId")
    @patch("window_picker.win32gui.GetWindowText")
    @patch("window_picker.win32gui.IsWindowVisible")
    @patch("window_picker.win32gui.EnumWindows")
    @patch("window_picker.os.getpid")
    def test_skips_untitled_and_own_process_windows(self, mock_getpid, mock_enum, mock_visible, mock_text, mock_pid):
        mock_getpid.return_value = 999
        windows = [(111, "Axonris Forge"), (222, ""), (333, "Notepad")]

        def fake_enum(cb, _):
            for hwnd, title in windows:
                cb(hwnd, None)

        def fake_text(hwnd):
            return dict((h, t) for h, t in windows)[hwnd]

        def fake_pid(hwnd):
            # hwnd 333 belongs to this own process (pid 999) -- must be skipped
            return (0, 999) if hwnd == 333 else (0, 1000)

        mock_enum.side_effect = fake_enum
        mock_visible.return_value = True
        mock_text.side_effect = fake_text
        mock_pid.side_effect = fake_pid

        result = wp.list_recordable_windows()
        titles = [w["title"] for w in result]
        self.assertIn("Axonris Forge", titles)
        self.assertNotIn("", titles)       # untitled skipped
        self.assertNotIn("Notepad", titles)  # own process skipped

    @patch("window_picker.win32process.GetWindowThreadProcessId")
    @patch("window_picker.win32gui.GetWindowText")
    @patch("window_picker.win32gui.IsWindowVisible")
    @patch("window_picker.win32gui.EnumWindows")
    @patch("window_picker.os.getpid")
    def test_skips_invisible_windows(self, mock_getpid, mock_enum, mock_visible, mock_text, mock_pid):
        mock_getpid.return_value = 999

        def fake_enum(cb, _):
            cb(111, None)

        mock_enum.side_effect = fake_enum
        mock_visible.return_value = False
        mock_text.return_value = "Hidden Window"
        mock_pid.return_value = (0, 1000)

        result = wp.list_recordable_windows()
        titles = [w["title"] for w in result]
        self.assertNotIn("Hidden Window", titles)

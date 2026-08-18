import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cursor_log as cl


class TestCursorLogger(unittest.TestCase):

    @patch("cursor_log.win32api.GetCursorPos")
    @patch("cursor_log.win32api.GetKeyState")
    def test_logs_positions_over_time(self, mock_key_state, mock_pos):
        mock_pos.return_value = (100, 200)
        mock_key_state.return_value = 0  # button not pressed

        logger = cl.CursorLogger()
        logger.start(interval_sec=0.01)
        time.sleep(0.05)
        entries = logger.stop()

        self.assertGreater(len(entries), 0)
        self.assertEqual(entries[0]["x"], 100)
        self.assertEqual(entries[0]["y"], 200)
        self.assertFalse(entries[0]["click"])

    @patch("cursor_log.win32api.GetCursorPos")
    @patch("cursor_log.win32api.GetKeyState")
    def test_detects_click_via_negative_key_state(self, mock_key_state, mock_pos):
        # win32api.GetKeyState returns a negative value when the button is
        # currently down (high bit set) -- this is the real win32 contract,
        # not a Video Studio invention.
        mock_pos.return_value = (50, 60)
        mock_key_state.return_value = -127

        logger = cl.CursorLogger()
        logger.start(interval_sec=0.01)
        time.sleep(0.03)
        entries = logger.stop()

        self.assertGreater(len(entries), 0)
        self.assertTrue(entries[0]["click"])

    @patch("cursor_log.win32api.GetCursorPos")
    @patch("cursor_log.win32api.GetKeyState")
    def test_stop_before_start_returns_empty(self, mock_key_state, mock_pos):
        logger = cl.CursorLogger()
        self.assertEqual(logger.stop(), [])

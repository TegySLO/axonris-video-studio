# tests/test_setup_wizard.py
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import setup_wizard as sw


class TestCheckPrerequisites(unittest.TestCase):

    @patch("setup_wizard.shutil.which")
    def test_all_present(self, mock_which):
        mock_which.side_effect = lambda name: f"/usr/bin/{name}"
        result = sw.check_prerequisites()
        self.assertTrue(result["node"])
        self.assertTrue(result["python"])
        self.assertTrue(result["ffmpeg"])

    @patch("setup_wizard.shutil.which")
    def test_ffmpeg_missing(self, mock_which):
        mock_which.side_effect = lambda name: None if name == "ffmpeg" else f"/usr/bin/{name}"
        result = sw.check_prerequisites()
        self.assertFalse(result["ffmpeg"])
        self.assertTrue(result["node"])

    @patch("setup_wizard.shutil.which")
    def test_none_present(self, mock_which):
        mock_which.return_value = None
        result = sw.check_prerequisites()
        self.assertEqual(result, {"node": False, "python": False, "ffmpeg": False})


class TestSetupWizardCloseButton(unittest.TestCase):

    def test_close_button_is_not_grayed(self):
        if sys.platform != "win32":
            self.skipTest("Windows-only check (native SC_CLOSE menu state)")
        import ctypes
        from PySide6.QtWidgets import QApplication, QDialog
        from PySide6.QtCore import QTimer

        app = QApplication.instance() or QApplication([])
        state_holder = {}
        orig_exec = QDialog.exec

        def patched_exec(self):
            def check_and_close():
                hwnd = int(self.winId())
                hmenu = ctypes.windll.user32.GetSystemMenu(hwnd, False)
                SC_CLOSE = 0xF060
                state_holder["state"] = ctypes.windll.user32.GetMenuState(hmenu, SC_CLOSE, 0)
                self.reject()
            QTimer.singleShot(50, check_and_close)
            return orig_exec(self)

        QDialog.exec = patched_exec
        try:
            sw.show_wizard()
        finally:
            QDialog.exec = orig_exec

        MF_GRAYED = 0x00000001
        self.assertIn("state", state_holder)
        self.assertFalse(state_holder["state"] & MF_GRAYED)

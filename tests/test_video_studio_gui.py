import os
import sys
import unittest

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

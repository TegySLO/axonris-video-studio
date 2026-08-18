"""video_studio_gui.py -- Axonris Video Studio main window.
Entry point for the compiled module_manifest.json's entry_exe
(video_studio_gui.exe, once built -- see Task 6+ in a follow-up plan for
the actual build step, matching axonris-sub-engine/build_sub_engine.py's
own Nuitka pattern)."""
from __future__ import annotations
import sys

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton,
)
from PySide6.QtGui import QFont


class _GeneratePage(QWidget):
    """Stub for Task 1 of the follow-up 'generate from description' plan --
    real template picker (concept-explainer-short / product-demo) and
    Claude Code invocation land there, not here."""

    def __init__(self, on_back):
        super().__init__()
        lay = QVBoxLayout(self)
        self._btn_back = QPushButton("← Back")
        self._btn_back.clicked.connect(on_back)
        lay.addWidget(self._btn_back)
        lay.addWidget(QLabel("Generate from description — coming soon."))
        lay.addStretch(1)


class _RecordPage(QWidget):
    """Stub for Task 1 of the follow-up 'record a tutorial' plan -- real
    screen-capture + auto-zoom + trim pipeline lands there, not here."""

    def __init__(self, on_back):
        super().__init__()
        lay = QVBoxLayout(self)
        self._btn_back = QPushButton("← Back")
        self._btn_back.clicked.connect(on_back)
        lay.addWidget(self._btn_back)
        lay.addWidget(QLabel("Record a tutorial — coming soon."))
        lay.addStretch(1)


class VideoStudioWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Axonris Video Studio")
        self.resize(900, 640)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._page_home = self._build_home_page()
        self._page_generate = _GeneratePage(on_back=self._go_home)
        self._page_record = _RecordPage(on_back=self._go_home)

        self._stack.addWidget(self._page_home)
        self._stack.addWidget(self._page_generate)
        self._stack.addWidget(self._page_record)
        self._stack.setCurrentWidget(self._page_home)

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(40, 40, 40, 40)
        lay.setSpacing(16)

        hdr = QLabel("🎬  Axonris Video Studio")
        hdr.setFont(QFont("Segoe UI", 22, QFont.Bold))
        lay.addWidget(hdr)

        row = QHBoxLayout()
        self._btn_generate = QPushButton("Generate from description")
        self._btn_generate.clicked.connect(lambda: self._stack.setCurrentWidget(self._page_generate))
        self._btn_record = QPushButton("Record a tutorial")
        self._btn_record.clicked.connect(lambda: self._stack.setCurrentWidget(self._page_record))
        row.addWidget(self._btn_generate)
        row.addWidget(self._btn_record)
        lay.addLayout(row)
        lay.addStretch(1)
        return page

    def _go_home(self):
        self._stack.setCurrentWidget(self._page_home)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Axonris Video Studio")

    from config import load_config
    from setup_wizard import show_wizard
    if not load_config().get("setup_wizard_seen"):
        show_wizard()

    win = VideoStudioWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

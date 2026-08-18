"""video_studio_gui.py -- Axonris Video Studio main window.
Entry point for the compiled module_manifest.json's entry_exe
(video_studio_gui.exe, once built -- see Task 6+ in a follow-up plan for
the actual build step, matching axonris-sub-engine/build_sub_engine.py's
own Nuitka pattern)."""
from __future__ import annotations
import os
import sys

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QComboBox, QProgressBar, QFileDialog,
)
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QFont

from window_picker import list_recordable_windows
from screen_recorder import start_recording
from zoom_polish import apply_zoom
from auto_cut import remove_silence


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


class _PostProcessWorker(QThread):
    """Runs stop -> zoom -> silence-cut off the GUI thread.

    These three stages spawn four ffmpeg passes and take minutes for a
    real-length recording; running them in the clicked-slot froze the
    whole window (the "Processing..." label could not even repaint,
    because no event-loop iteration happened between setText and the
    blocking work). Any failure is reported through result_signal instead
    of escaping the slot -- previously an ffmpeg error left BOTH buttons
    disabled with the status stuck on "Processing...", i.e. a dead page
    until the app was restarted."""

    result_signal = Signal(bool, str)

    def __init__(self, recording, output_dir: str):
        super().__init__()
        self._recording = recording
        self._output_dir = output_dir

    def run(self):
        try:
            session = self._recording.stop()
            # os.path.basename + join, not a whole-path str.replace(): the
            # old form also rewrote the DIRECTORY component whenever the
            # chosen output folder happened to contain "raw_capture_" or
            # "zoomed_", producing a path that does not exist.
            base = os.path.basename(session.raw_video_path)
            zoomed_path = os.path.join(self._output_dir, base.replace("raw_capture_", "zoomed_", 1))
            final_path = os.path.join(self._output_dir, base.replace("raw_capture_", "final_", 1))
            apply_zoom(session, zoomed_path)
            remove_silence(zoomed_path, final_path)
            self.result_signal.emit(True, final_path)
        except Exception as exc:  # noqa: BLE001 -- must reach the UI, whatever it is
            self.result_signal.emit(False, f"{type(exc).__name__}: {exc}")


class _RecordPage(QWidget):
    """Record a tutorial: pick a window/screen, record, then auto-polish
    (cursor-driven zoom + silence-based auto-cut) into a finished MP4.
    No Claude Code/cloud GPU account needed -- pure local recording and
    ffmpeg post-processing, distinct from _GeneratePage's BYOK path."""

    def __init__(self, on_back):
        super().__init__()
        self._active_recording = None
        self._output_dir = None
        self._worker = None

        lay = QVBoxLayout(self)
        self._btn_back = QPushButton("← Back")
        self._btn_back.clicked.connect(on_back)
        lay.addWidget(self._btn_back)

        lay.addWidget(QLabel("Record a tutorial"))

        row = QHBoxLayout()
        self._window_combo = QComboBox()
        self._window_combo.currentIndexChanged.connect(self._on_selection_changed)
        row.addWidget(self._window_combo)

        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.clicked.connect(self.refresh_window_list)
        row.addWidget(self._btn_refresh)
        lay.addLayout(row)

        action_row = QHBoxLayout()
        self._btn_start = QPushButton("Start Recording")
        self._btn_start.setEnabled(False)
        self._btn_start.clicked.connect(self._on_start_clicked)
        action_row.addWidget(self._btn_start)

        self._btn_stop = QPushButton("Stop && Polish")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop_clicked)
        action_row.addWidget(self._btn_stop)
        lay.addLayout(action_row)

        self._status_lbl = QLabel("")
        lay.addWidget(self._status_lbl)
        lay.addStretch(1)

        self.refresh_window_list()

    def refresh_window_list(self):
        self._window_combo.clear()
        for entry in list_recordable_windows():
            self._window_combo.addItem(entry["title"], entry)
        self._on_selection_changed()

    def _on_selection_changed(self):
        self._btn_start.setEnabled(self._window_combo.count() > 0)

    def _on_start_clicked(self):
        target = self._window_combo.currentData()
        if target is None:
            return
        output_dir = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if not output_dir:
            return
        self._output_dir = output_dir
        self._active_recording = start_recording(target, output_dir)
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._status_lbl.setText("Recording...")

    def _on_stop_clicked(self):
        if self._active_recording is None:
            return
        self._status_lbl.setText("Processing (zoom + silence cut)...")
        self._btn_stop.setEnabled(False)

        self._worker = _PostProcessWorker(self._active_recording, self._output_dir)
        self._active_recording = None
        self._worker.result_signal.connect(self._on_processing_finished)
        self._worker.start()

    def _on_processing_finished(self, ok: bool, message: str):
        self._status_lbl.setText(f"Done: {message}" if ok else f"Failed: {message}")
        self._btn_start.setEnabled(self._window_combo.count() > 0)
        self._worker = None

    def shutdown(self):
        """Stop anything still running before the window closes -- an
        in-flight recording would otherwise leave its ffmpeg child
        unreaped and the WASAPI stream open, and an in-flight
        post-processing worker would be killed mid-pass by interpreter
        exit, orphaning its ffmpeg."""
        recording, self._active_recording = self._active_recording, None
        if recording is not None:
            try:
                recording.stop()
            except Exception:
                pass
        worker = self._worker
        if worker is not None and worker.isRunning():
            # Let the current ffmpeg pass finish rather than orphan it.
            if not worker.wait(30000):
                worker.terminate()
                worker.wait(2000)
        self._worker = None


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

    def closeEvent(self, event):
        self._page_record.shutdown()
        super().closeEvent(event)


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

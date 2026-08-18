"""cursor_log.py -- background cursor-position + click logger, used by
screen_recorder.py during capture and zoom_polish.py afterward to decide
zoom targets. Separate module (not inlined into screen_recorder.py) since
zoom_polish.py needs the log's shape/format without needing the rest of
the capture machinery."""
from __future__ import annotations
import threading
import time

import win32api

_VK_LBUTTON = 0x01


class CursorLogger:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._entries: list[dict] = []

    def start(self, interval_sec: float = 0.05) -> None:
        self._entries = []
        self._stop_event.clear()
        start_time = time.monotonic()

        def _loop():
            while not self._stop_event.is_set():
                x, y = win32api.GetCursorPos()
                # GetKeyState returns a value with the high bit set (negative
                # as a signed short) when the key/button is currently down --
                # real win32 contract, not something this module invents.
                clicked = win32api.GetKeyState(_VK_LBUTTON) < 0
                self._entries.append({
                    "t": time.monotonic() - start_time,
                    "x": x, "y": y, "click": clicked,
                })
                time.sleep(interval_sec)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> list[dict]:
        if self._thread is None:
            return []
        self._stop_event.set()
        self._thread.join(timeout=2.0)
        return self._entries

"""window_picker.py -- lists recordable top-level windows for Axonris
Video Studio's "Record a tutorial" path. Same win32gui.EnumWindows
technique already proven this session (Hub sandboxed install test) --
no new dependency, pywin32 is already a working import in this
environment."""
from __future__ import annotations
import os

import win32gui
import win32process


def list_recordable_windows() -> list[dict]:
    """Returns [{"hwnd": None, "title": "Full screen"}, ...real windows].
    Skips invisible windows, untitled windows, and this process's own
    windows (recording your own picker dialog would be useless)."""
    own_pid = os.getpid()
    found = [{"hwnd": None, "title": "Full screen"}]

    def _callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid == own_pid:
            return True
        found.append({"hwnd": hwnd, "title": title})
        return True

    win32gui.EnumWindows(_callback, None)
    return found

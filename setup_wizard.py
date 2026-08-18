"""setup_wizard.py -- first-run BYOK setup wizard for Axonris Video Studio.
Mirrors axonris-sub-engine/onboarding_wizard.py's own principles: progressive
disclosure, cost-transparent, skippable, idempotent (same as
claude-code-video-toolkit's own /setup command, .claude/commands/setup.md --
verified locally at Desktop\\snemanje\\claude-code-video-toolkit).

BUG CLASS TO AVOID (this session's own real fix, axonris-sub-engine/onboarding_wizard.py,
2026-08-18): stripping Qt.WindowContextHelpButtonHint via bitwise AND-NOT on
Windows disables the native close (X) button. This wizard's dialog construction
(Step 9 below) ORs Qt.WindowCloseButtonHint back in explicitly instead of
relying on it implicitly -- do not repeat that bug here.
"""
from __future__ import annotations
import shutil


def check_prerequisites() -> dict:
    """Returns {"node": bool, "python": bool, "ffmpeg": bool} -- pure PATH
    lookup, no version parsing yet (matches claude-code-video-toolkit's own
    Step 1 "Detect Current State", which also starts with a plain existence
    check before checking versions)."""
    return {
        "node": shutil.which("node") is not None,
        "python": shutil.which("python") is not None or shutil.which("python3") is not None,
        "ffmpeg": shutil.which("ffmpeg") is not None,
    }


def show_wizard(parent=None) -> bool:
    """First-run setup dialog. Cost-transparent (states what's free vs paid
    before any action, matching claude-code-video-toolkit's own "Cost
    transparency" setup principle), skippable at every step, idempotent
    (safe to run again -- re-checks current state each time instead of
    assuming a fresh install)."""
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    )
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont

    dlg = QDialog(parent)
    dlg.setWindowTitle("Axonris Video Studio — Setup")
    dlg.setMinimumSize(520, 400)
    # Explicit OR of WindowCloseButtonHint -- see this file's module
    # docstring for why the naive "& ~ContextHelpButtonHint" form is unsafe.
    dlg.setWindowFlags((dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint) | Qt.WindowCloseButtonHint)

    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(32, 28, 32, 24)
    lay.setSpacing(12)

    hdr = QLabel("🎬  Axonris Video Studio Setup")
    hdr.setFont(QFont("Segoe UI", 18, QFont.Bold))
    lay.addWidget(hdr)

    result = [False]
    prereqs = check_prerequisites()

    status_lines = []
    for name, ok in prereqs.items():
        icon = "✅" if ok else "⚠"
        status_lines.append(f"{icon}  {name.capitalize()} {'found' if ok else 'not found'}")
    status_lbl = QLabel("\n".join(status_lines))
    status_lbl.setWordWrap(True)
    lay.addWidget(status_lbl)

    cost_note = QLabel(
        "Generation uses your own Claude Code account plus a cloud GPU "
        "provider (Modal has a free $30/month starter tier). Video Studio "
        "itself is always free — you only pay if/what your own provider "
        "accounts charge."
    )
    cost_note.setWordWrap(True)
    cost_note.setStyleSheet("color: #71717A; font-size: 12px;")
    lay.addWidget(cost_note)

    btn_row = QHBoxLayout()
    btn_skip = QPushButton("Skip for now")
    btn_continue = QPushButton("Continue")
    btn_row.addWidget(btn_skip)
    btn_row.addWidget(btn_continue)
    lay.addLayout(btn_row)

    def _skip():
        result[0] = False
        dlg.reject()

    def _continue():
        from config import save_config
        save_config({"setup_wizard_seen": True, **{f"{k}_ok": v for k, v in prereqs.items()}})
        result[0] = True
        dlg.accept()

    btn_skip.clicked.connect(_skip)
    btn_continue.clicked.connect(_continue)

    dlg.exec()
    return result[0]

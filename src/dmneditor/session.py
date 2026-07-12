"""Autosave + session-recovery.

Storage (under QStandardPaths.AppDataLocation, e.g. %APPDATA%\\dmn-editor\\):
  session.json        - {"slots": {autosave_id: {real_path, autosave_id, dirty}}}
  autosave/<id>.txt    - full-buffer dump of a dirty document's current text

The real file the user explicitly Saves/Saves-As to is untouched by any of
this except that its slot's autosave copy is deleted once it's no longer
needed (the real file becomes authoritative again).
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtWidgets import QTextEdit

AUTOSAVE_INTERVAL_MS = 5000


def _app_data_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    d = Path(base)
    (d / "autosave").mkdir(parents=True, exist_ok=True)
    return d


def _session_path() -> Path:
    return _app_data_dir() / "session.json"


def _autosave_path(autosave_id: str) -> Path:
    return _app_data_dir() / "autosave" / f"{autosave_id}.txt"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def _load_session_file() -> dict:
    path = _session_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_session_file(data: dict) -> None:
    _atomic_write(_session_path(), json.dumps(data, indent=2))


class DocumentSession:
    """Recovery identity for a single open document/window."""

    def __init__(self, real_path: Optional[str] = None, autosave_id: Optional[str] = None):
        self.real_path = real_path
        self.autosave_id = autosave_id or str(uuid.uuid4())
        self.dirty = False
        # Caret character offset, so a recovered document reopens scrolled to
        # where you left off instead of at the top.
        self.cursor_pos = 0

    def to_dict(self) -> dict:
        return {
            "real_path": self.real_path,
            "autosave_id": self.autosave_id,
            "dirty": self.dirty,
            "cursor_pos": self.cursor_pos,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DocumentSession":
        s = cls(real_path=d.get("real_path"), autosave_id=d.get("autosave_id"))
        s.dirty = bool(d.get("dirty", False))
        # Default 0 keeps slots written before this feature working.
        s.cursor_pos = int(d.get("cursor_pos") or 0)
        return s


def pending_recovery_slots() -> list[DocumentSession]:
    """Slots left over from a previous run that still have unsaved content."""
    data = _load_session_file()
    return [
        DocumentSession.from_dict(d)
        for d in data.get("slots", {}).values()
        if d.get("dirty")
    ]


def load_autosave_text(doc_session: DocumentSession) -> Optional[str]:
    path = _autosave_path(doc_session.autosave_id)
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


class SessionManager:
    """Owns the autosave timer + recovery-slot bookkeeping for one open document."""

    def __init__(self, editor: QTextEdit, doc_session: DocumentSession):
        self.editor = editor
        self.doc_session = doc_session
        self._timer = QTimer()
        self._timer.setInterval(AUTOSAVE_INTERVAL_MS)
        self._timer.timeout.connect(self._flush_if_dirty)
        self._timer.start()

    def _flush_if_dirty(self) -> None:
        if self.editor.document().isModified():
            self.flush()

    def flush(self) -> None:
        self.doc_session.cursor_pos = self.editor.textCursor().position()
        _atomic_write(_autosave_path(self.doc_session.autosave_id), self.editor.toPlainText())
        self.doc_session.dirty = True
        self._persist_entry()

    def mark_saved(self, real_path: str) -> None:
        """Call after an explicit Save/Save As writes `real_path` successfully."""
        self.doc_session.real_path = real_path
        self.doc_session.dirty = False
        autosave_file = _autosave_path(self.doc_session.autosave_id)
        if autosave_file.exists():
            try:
                autosave_file.unlink()
            except OSError:
                pass
        self._persist_entry()

    def close(self) -> None:
        """Force-flush so a window close never races the autosave timer."""
        self._timer.stop()
        self.doc_session.cursor_pos = self.editor.textCursor().position()
        if self.editor.document().isModified():
            self.flush()
        else:
            self._persist_entry()

    def forget(self) -> None:
        """Drop this slot entirely - used when there's nothing worth recovering."""
        data = _load_session_file()
        data.get("slots", {}).pop(self.doc_session.autosave_id, None)
        _save_session_file(data)
        autosave_file = _autosave_path(self.doc_session.autosave_id)
        if autosave_file.exists():
            try:
                autosave_file.unlink()
            except OSError:
                pass

    def _persist_entry(self) -> None:
        data = _load_session_file()
        slots = data.setdefault("slots", {})
        slots[self.doc_session.autosave_id] = self.doc_session.to_dict()
        _save_session_file(data)

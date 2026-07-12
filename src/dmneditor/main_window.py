"""MainWindow: File New/Open/Save/Save As, title/modified indicator, and
wiring the editor widget to session recovery. Single document per window,
like classic Notepad - no forced "save changes?" dialogs anywhere, since
autosave/session-recovery already guarantees nothing is lost (matching
Notepad++ / Windows 11 Notepad's silent-recovery model).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox

from . import session, settings
from .editor_widget import OutlineEditor


class MainWindow(QMainWindow):
    def __init__(
        self,
        doc_session: Optional[session.DocumentSession] = None,
        recovered_text: Optional[str] = None,
    ):
        super().__init__()
        self.resize(900, 700)

        self.editor = OutlineEditor(self)
        self.setCentralWidget(self.editor)

        self._current_path: Optional[str] = None
        self._doc_session = self._init_session(doc_session, recovered_text)
        self._session_manager = session.SessionManager(self.editor, self._doc_session)

        self.editor.document().modificationChanged.connect(self._update_title)
        self._build_menu()
        self._restore_geometry()
        self._update_title()

    # ------------------------------------------------------------------
    def _init_session(
        self,
        doc_session: Optional[session.DocumentSession],
        recovered_text: Optional[str],
    ) -> session.DocumentSession:
        # Recovery slot selection now happens once, at startup, in
        # open_startup_windows() - which opens one window per recoverable
        # document. This window just loads whatever it was handed (or a
        # blank doc when nothing was).
        if doc_session is not None and recovered_text is not None:
            self.editor.set_document_text(recovered_text)
            self.editor.document().setModified(True)
            self._current_path = doc_session.real_path
            self.editor.restore_cursor_position(doc_session.cursor_pos)
            return doc_session
        # Always route through set_document_text, even for a blank new
        # document, so the trailing-newline normalization (and the
        # reorder-safe sentinel block it guarantees) always applies.
        self.editor.set_document_text("")
        return session.DocumentSession()

    def _restore_geometry(self) -> None:
        geometry = settings.load_geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        new_action = QAction("&New", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self.new_file)
        file_menu.addAction(new_action)

        open_action = QAction("&Open...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_file)
        file_menu.addAction(open_action)

        save_action = QAction("&Save", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save_file)
        file_menu.addAction(save_action)

        save_as_action = QAction("Save &As...", self)
        save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_as_action.triggered.connect(self.save_file_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()
        discard_action = QAction("&Discard (no recovery)", self)
        discard_action.setShortcut(QKeySequence("Ctrl+Shift+W"))
        discard_action.triggered.connect(self.discard_document)
        file_menu.addAction(discard_action)

        self._build_shortcuts_menu()

    def _build_shortcuts_menu(self) -> None:
        """A read-only cheat sheet of every keybinding, sitting to the right
        of the File menu. Entries are disabled QActions - they're reference
        text, not commands, and the real bindings live in the editor's key
        funnel / File menu.
        """
        menu = self.menuBar().addMenu("&Shortcuts")
        groups = [
            ("File", [
                ("Ctrl+N", "New"),
                ("Ctrl+O", "Open"),
                ("Ctrl+S", "Save"),
                ("Ctrl+Shift+S", "Save As"),
                ("Ctrl+Shift+W", "Discard document (no recovery)"),
            ]),
            ("Editing", [
                ("Enter", "New line (carry indent; 2nd Enter on empty line outdents)"),
                ("Tab", "Indent line / selection"),
                ("Shift+Tab", "Outdent line / selection"),
                ("Backspace", "Outdent (at start of an indented line)"),
                ("Ctrl+T", "Insert / refresh timestamp"),
                ("Alt+Up / Alt+Down", "Move line up / down"),
                ("Ctrl+Alt+Up / Down", "Move line + its subtree"),
            ]),
            ("View", [
                ("Ctrl+Shift+C", "Compress: collapse blank lines (toggle)"),
                ("Ctrl+= / Ctrl+-", "Zoom in / out (font size)"),
                ("Ctrl+0", "Reset zoom"),
                ("Ctrl+Mouse Wheel", "Zoom in / out"),
            ]),
        ]
        for title, entries in groups:
            menu.addSection(title)
            for keys, desc in entries:
                action = QAction(f"{keys}  -  {desc}", self)
                action.setEnabled(False)
                menu.addAction(action)

    # ------------------------------------------------------------------
    def _update_title(self, *_args) -> None:
        name = Path(self._current_path).name if self._current_path else "Untitled"
        modified = "*" if self.editor.document().isModified() else ""
        self.setWindowTitle(f"{modified}{name} - Outline Editor")

    def _retire_current_session(self) -> None:
        self._session_manager.close()
        if not self.editor.document().isModified():
            self._session_manager.forget()

    def new_file(self) -> None:
        self._retire_current_session()
        self._current_path = None
        self.editor.set_document_text("")
        self._doc_session = session.DocumentSession()
        self._session_manager = session.SessionManager(self.editor, self._doc_session)
        self._update_title()

    def discard_document(self) -> None:
        """Throw the current document away without keeping it recoverable, then
        start a fresh blank one. For abandoned scratch outlines that would
        otherwise reopen on every launch. Confirms first (Enter discards, Esc
        cancels) since the content is gone for good afterward."""
        reply = QMessageBox.warning(
            self,
            "Discard document",
            "Discard this document? It will not be recoverable.",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Discard,
        )
        if reply != QMessageBox.StandardButton.Discard:
            return
        self._session_manager.discard()
        self._current_path = None
        self.editor.set_document_text("")
        self._doc_session = session.DocumentSession()
        self._session_manager = session.SessionManager(self.editor, self._doc_session)
        self._update_title()

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open", "", "Text Files (*.txt);;All Files (*)")
        if not path:
            return
        text = Path(path).read_text(encoding="utf-8")
        self._retire_current_session()
        self.editor.set_document_text(text)
        self._current_path = path
        self._doc_session = session.DocumentSession(real_path=path)
        self._session_manager = session.SessionManager(self.editor, self._doc_session)
        self._update_title()

    def save_file(self) -> bool:
        if not self._current_path:
            return self.save_file_as()
        self._write_to_path(self._current_path)
        return True

    def save_file_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Save As", "", "Text Files (*.txt);;All Files (*)")
        if not path:
            return False
        self._write_to_path(path)
        return True

    def _write_to_path(self, path: str) -> None:
        session._atomic_write(Path(path), self.editor.toPlainText())
        self._current_path = path
        self.editor.document().setModified(False)
        self._session_manager.mark_saved(path)
        self._update_title()

    # ------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        settings.save_geometry(self.saveGeometry())
        self._retire_current_session()
        event.accept()


def open_startup_windows() -> list["MainWindow"]:
    """Recover *every* unsaved document left over from the previous run -
    one window each - instead of only the first.

    The old path recovered just recoverable[0], silently orphaning any
    second-or-later dirty document. With more than one unsaved doc that made
    a newer document appear to be "replaced" by an older one on restart (the
    newer one was still safe on disk, just never surfaced). If nothing is
    recoverable, open a single blank window.
    """
    windows: list[MainWindow] = []
    for doc_session in session.pending_recovery_slots():
        text = session.load_autosave_text(doc_session)
        if text is None:
            continue  # autosave file gone - nothing to restore for this slot
        windows.append(MainWindow(doc_session=doc_session, recovered_text=text))
    if not windows:
        windows.append(MainWindow())
    return windows

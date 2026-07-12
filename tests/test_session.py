import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from dmneditor import session


@pytest.fixture(autouse=True)
def isolated_app_data(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "_app_data_dir", lambda: tmp_path)
    (tmp_path / "autosave").mkdir(exist_ok=True)
    yield tmp_path


def test_atomic_write_and_read_roundtrip(tmp_path):
    path = tmp_path / "sub" / "out.txt"
    session._atomic_write(path, "hello\nworld\n")
    assert path.read_text(encoding="utf-8") == "hello\nworld\n"


def test_document_session_dict_roundtrip():
    s = session.DocumentSession(real_path="C:/notes.txt")
    d = s.to_dict()
    s2 = session.DocumentSession.from_dict(d)
    assert s2.real_path == s.real_path
    assert s2.autosave_id == s.autosave_id
    assert s2.dirty == s.dirty


def test_document_session_persists_cursor_pos():
    s = session.DocumentSession(real_path="C:/notes.txt")
    s.cursor_pos = 42
    s2 = session.DocumentSession.from_dict(s.to_dict())
    assert s2.cursor_pos == 42


def test_document_session_cursor_pos_defaults_zero_for_legacy_slots():
    # Slots written before this feature have no cursor_pos key.
    s = session.DocumentSession.from_dict(
        {"real_path": None, "autosave_id": "x", "dirty": True}
    )
    assert s.cursor_pos == 0


def test_no_pending_recovery_when_session_file_absent():
    assert session.pending_recovery_slots() == []


def test_pending_recovery_returns_only_dirty_slots():
    data = {
        "slots": {
            "a": {"real_path": None, "autosave_id": "a", "dirty": True},
            "b": {"real_path": "C:/x.txt", "autosave_id": "b", "dirty": False},
        }
    }
    session._save_session_file(data)
    pending = session.pending_recovery_slots()
    assert len(pending) == 1
    assert pending[0].autosave_id == "a"


def test_load_autosave_text_missing_returns_none():
    s = session.DocumentSession()
    assert session.load_autosave_text(s) is None


def test_load_autosave_text_reads_written_buffer(tmp_path):
    s = session.DocumentSession()
    session._atomic_write(session._autosave_path(s.autosave_id), "02:15p hi\n")
    assert session.load_autosave_text(s) == "02:15p hi\n"

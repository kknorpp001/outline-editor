"""Lightweight app preferences (window geometry) via QSettings.

Document content and recovery state live in session.py, not here.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QByteArray, QSettings

ORG_NAME = "dmn-editor"
APP_NAME = "OutlineEditor"


def _settings() -> QSettings:
    return QSettings(ORG_NAME, APP_NAME)


def save_geometry(geometry: QByteArray) -> None:
    _settings().setValue("window/geometry", geometry)


def load_geometry() -> Optional[QByteArray]:
    value = _settings().value("window/geometry")
    return value if value else None

"""Pure, Qt-free logic for the outline editor.

Everything here operates on plain strings/ints/enums so it can be unit
tested without a QApplication. The Qt adapter layer lives in
editor_widget.py and translates these decisions into QTextCursor edits.
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum, auto
from typing import Optional

INDENT_CHAR = "\t"

# Anchored to the start of a line's *content* (after stripping the leading
# tab indent) - must use re.match (never re.search) against exactly that
# substring, never the whole block/document text, or it will false-match
# arbitrary user-typed digit patterns elsewhere in a line.
TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}[ap] ")


def indent_prefix_len(line: str) -> int:
    """Number of leading tab characters on a line."""
    return len(line) - len(line.lstrip(INDENT_CHAR))


def indent_level(line: str) -> int:
    """One indent level == one leading tab character."""
    return indent_prefix_len(line)


def line_content(line: str) -> str:
    """The line's text after stripping its leading tab indent."""
    return line[indent_prefix_len(line):]


def line_has_timestamp(line: str) -> bool:
    return bool(TIMESTAMP_RE.match(line_content(line)))


def line_is_empty_of_content(line: str) -> bool:
    """True if the line has no timestamp and no typed text yet (indent-only or blank)."""
    return line_content(line) == ""


def format_timestamp(dt: datetime) -> str:
    """e.g. 02:15p, 12:00a, 12:00p - no trailing space (callers append the separator space)."""
    hour12 = dt.hour % 12 or 12
    ampm = "a" if dt.hour < 12 else "p"
    return f"{hour12:02d}:{dt.minute:02d}{ampm}"


def indent_line(line: str) -> str:
    return INDENT_CHAR + line


def outdent_line(line: str) -> str:
    if line.startswith(INDENT_CHAR):
        return line[1:]
    return line


def apply_timestamp_refresh(text: str, cursor_col: int, new_stamp: str) -> tuple[str, int]:
    """Insert-or-replace the leading timestamp token on `text` with `new_stamp`.

    Returns (new_text, new_cursor_col). `cursor_col` and the returned column
    are offsets into `text`/`new_text` (0 = start of line). If the cursor sat
    inside the old timestamp token, it's clamped to just after the new one
    rather than preserving a now-meaningless offset.
    """
    indent_len = indent_prefix_len(text)
    rest = text[indent_len:]
    m = TIMESTAMP_RE.match(rest)
    old_token_len = m.end() if m else 0
    new_token = new_stamp + " "
    new_rest = new_token + rest[old_token_len:]
    new_text = text[:indent_len] + new_rest

    if indent_len < cursor_col < indent_len + old_token_len:
        new_col = indent_len + len(new_token)
    elif cursor_col < indent_len:
        new_col = cursor_col
    else:
        delta = len(new_token) - old_token_len
        new_col = cursor_col + delta

    new_col = max(0, min(new_col, len(new_text)))
    return new_text, new_col


class BlankLineAction(Enum):
    NONE = auto()
    INSERT = auto()
    REMOVE = auto()


def compute_blank_line_action(
    new_level: int,
    neighbor_text: Optional[str],
    beyond_text: Optional[str],
) -> BlankLineAction:
    """Decide whether the boundary on one side of a line whose indent level
    just changed to `new_level` needs a blank-line separator inserted or
    removed, to maintain the invariant "a blank line separates two lines
    only when their indent levels differ."

    Generic/one-directional - called twice per indent-changing edit, once
    for the boundary above (neighbor_text=prev line, beyond_text=prev-prev
    line) and once for the boundary below (neighbor_text=next line,
    beyond_text=next-next line). Applies regardless of whether the edited
    line already has content - the invariant is purely structural.
    """
    if neighbor_text is None:
        return BlankLineAction.NONE

    if neighbor_text == "":
        if beyond_text is not None and indent_level(beyond_text) == new_level:
            return BlankLineAction.REMOVE
        return BlankLineAction.NONE

    if indent_level(neighbor_text) != new_level:
        return BlankLineAction.INSERT

    return BlankLineAction.NONE

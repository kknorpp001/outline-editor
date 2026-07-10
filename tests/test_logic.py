import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dmneditor import logic


# --- indent / content helpers -------------------------------------------------

def test_indent_level_counts_leading_tabs():
    assert logic.indent_level("") == 0
    assert logic.indent_level("\thello") == 1
    assert logic.indent_level("\t\t\thello") == 3


def test_line_content_strips_leading_tabs_only():
    assert logic.line_content("\t\t02:15p hi") == "02:15p hi"
    assert logic.line_content("no indent") == "no indent"


def test_line_is_empty_of_content():
    assert logic.line_is_empty_of_content("")
    assert logic.line_is_empty_of_content("\t\t")
    assert not logic.line_is_empty_of_content("\tx")
    assert not logic.line_is_empty_of_content("02:15p x")


# --- timestamp formatting -------------------------------------------------

def test_format_timestamp_midday_and_midnight():
    assert logic.format_timestamp(datetime(2026, 1, 1, 0, 0)) == "12:00a"
    assert logic.format_timestamp(datetime(2026, 1, 1, 12, 0)) == "12:00p"
    assert logic.format_timestamp(datetime(2026, 1, 1, 13, 5)) == "01:05p"
    assert logic.format_timestamp(datetime(2026, 1, 1, 23, 59)) == "11:59p"
    assert logic.format_timestamp(datetime(2026, 1, 1, 9, 3)) == "09:03a"


def test_line_has_timestamp_requires_anchored_trailing_space():
    assert logic.line_has_timestamp("02:15p hello")
    assert logic.line_has_timestamp("\t\t02:15p hello")
    assert not logic.line_has_timestamp("02:15pFoo")  # no separator space
    assert not logic.line_has_timestamp("hello 02:15p world")  # not anchored at start
    assert not logic.line_has_timestamp("hello")


def test_timestamp_regex_does_not_false_match_mid_line_digits():
    # A user typing something that merely contains an HH:MM-shaped substring
    # mid-line must not register as "line has timestamp".
    assert not logic.line_has_timestamp("call at 02:15p tomorrow")


# --- Ctrl+T refresh-in-place -------------------------------------------------

def test_apply_timestamp_refresh_inserts_on_line_with_no_existing_stamp():
    new_text, new_col = logic.apply_timestamp_refresh("hello", cursor_col=5, new_stamp="03:00p")
    assert new_text == "03:00p hello"
    assert new_col == 5 + len("03:00p ")


def test_apply_timestamp_refresh_replaces_existing_stamp_preserves_trailing_text():
    new_text, new_col = logic.apply_timestamp_refresh(
        "02:15p hello world", cursor_col=len("02:15p hello"), new_stamp="03:00p"
    )
    assert new_text == "03:00p hello world"
    # same delta (both stamps same length here) so column preserved exactly
    assert new_col == len("03:00p hello")


def test_apply_timestamp_refresh_respects_indent_prefix():
    new_text, new_col = logic.apply_timestamp_refresh("\t\t02:15p hi", cursor_col=2, new_stamp="03:00p")
    assert new_text == "\t\t03:00p hi"
    assert new_col == 2  # cursor was before the stamp (inside indent), stays put


def test_apply_timestamp_refresh_clamps_cursor_inside_old_token():
    text = "02:15p hello"
    # cursor sitting inside "02:15p " (col 3, inside "15p ")
    new_text, new_col = logic.apply_timestamp_refresh(text, cursor_col=3, new_stamp="11:59p")
    assert new_text == "11:59p hello"
    assert new_col == len("11:59p ")


def test_apply_timestamp_refresh_on_empty_indent_only_line():
    new_text, new_col = logic.apply_timestamp_refresh("\t\t", cursor_col=2, new_stamp="03:00p")
    assert new_text == "\t\t03:00p "
    assert new_col == len("\t\t03:00p ")
    assert logic.line_has_timestamp(new_text)  # next real keystroke won't double-stamp


# --- blank-line separator invariant -------------------------------------------------
# compute_blank_line_action is generic/one-directional: called once for the
# boundary above a line (neighbor=prev, beyond=prev-prev) and once for the
# boundary below (neighbor=next, beyond=next-next). Applies regardless of
# whether the edited line has content - it's a purely structural invariant.

def test_blank_line_none_when_no_neighbor():
    # top of document (no prev) / end of document (no next)
    action = logic.compute_blank_line_action(new_level=0, neighbor_text=None, beyond_text=None)
    assert action == logic.BlankLineAction.NONE


def test_blank_line_insert_when_neighbor_level_differs():
    action = logic.compute_blank_line_action(
        new_level=1, neighbor_text="02:15p top level", beyond_text=None,
    )
    assert action == logic.BlankLineAction.INSERT


def test_blank_line_none_when_neighbor_level_matches():
    action = logic.compute_blank_line_action(
        new_level=1, neighbor_text="\t02:15p sibling", beyond_text=None,
    )
    assert action == logic.BlankLineAction.NONE


def test_blank_line_none_when_already_separated_and_still_needed():
    # neighbor is an existing blank separator; the line beyond it is at a
    # different level, so the separator is still doing its job -> leave it
    action = logic.compute_blank_line_action(
        new_level=2, neighbor_text="", beyond_text="02:15p top",
    )
    assert action == logic.BlankLineAction.NONE


def test_blank_line_remove_when_separator_now_redundant():
    # e.g. Tab (inserted blank, level 1) then immediate Shift+Tab back to
    # level 0 - or an outdent long after typing, back down to a level that
    # now matches the line on the far side of an existing blank separator.
    action = logic.compute_blank_line_action(
        new_level=0, neighbor_text="", beyond_text="02:15p top",
    )
    assert action == logic.BlankLineAction.REMOVE


def test_blank_line_none_when_beyond_missing():
    # neighbor is blank but it's the very edge of the document (nothing past it)
    action = logic.compute_blank_line_action(new_level=0, neighbor_text="", beyond_text=None)
    assert action == logic.BlankLineAction.NONE

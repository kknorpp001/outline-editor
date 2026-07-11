"""The custom outline text-editor widget.

Thin Qt adapter: all decision logic lives in logic.py (pure, testable);
this module translates those decisions into QTextCursor edits and owns
the keyPressEvent funnel for the app's custom keybindings.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeyEvent, QTextBlock, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit

from . import logic

FONT_FAMILY = "Consolas"
FONT_POINT_SIZE = 18


class OutlineEditor(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)

        font = QFont(FONT_FAMILY, FONT_POINT_SIZE)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self.setFont(font)

        # One indent level = the width of a timestamp token ("00:00a "),
        # so an indented line's timestamp visually lines up with the first
        # word of the line above it.
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance("00:00a "))

    def set_document_text(self, text: str) -> None:
        if not text.endswith("\n"):
            text += "\n"
        self.setPlainText(text)
        block = self.document().begin()
        while block.isValid():
            self._apply_hanging_indent(block)
            block = block.next()
        self.document().clearUndoRedoStacks()
        self.document().setModified(False)

    def _apply_hanging_indent(self, block: QTextBlock) -> None:
        """Wrapped continuation lines align under where this line's actual
        text starts - after its leading tabs and, if present, its
        timestamp - rather than back at column 0.
        """
        text = block.text()
        margin = logic.indent_prefix_len(text) * self.tabStopDistance()
        if logic.line_has_timestamp(text):
            margin += self.fontMetrics().horizontalAdvance("00:00a ")

        fmt = block.blockFormat()
        fmt.setLeftMargin(margin)
        fmt.setTextIndent(-margin)
        QTextCursor(block).setBlockFormat(fmt)

    # ------------------------------------------------------------------
    # key event funnel
    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        if key == Qt.Key.Key_T and ctrl and not alt:
            self._refresh_timestamp()
            event.accept()
            return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not ctrl and not alt and not shift:
            self._handle_enter()
            event.accept()
            return

        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and alt:
            direction = -1 if key == Qt.Key.Key_Up else 1
            self._move_lines(direction, with_subtree=ctrl)
            event.accept()
            return

        if key == Qt.Key.Key_Tab and not ctrl and not alt and not shift:
            self._indent_selection_or_line(+1)
            event.accept()
            return

        if key == Qt.Key.Key_Backtab or (key == Qt.Key.Key_Tab and shift):
            self._indent_selection_or_line(-1)
            event.accept()
            return

        if key == Qt.Key.Key_Backspace and not ctrl and not alt:
            if self._try_backspace_outdent():
                event.accept()
                return

        if event.text() and event.text().isprintable():
            if self._first_keystroke_stamp_if_needed(event):
                return

        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # timestamp: first keystroke auto-insert
    # ------------------------------------------------------------------
    def _first_keystroke_stamp_if_needed(self, event: QKeyEvent) -> bool:
        """If about to type the first character on a content-empty line,
        insert the auto-timestamp first, in the same undo step as the
        keystroke. Returns True if it already delegated to super()."""
        cursor = self.textCursor()
        block = cursor.block()

        if not logic.line_is_empty_of_content(block.text()):
            return False

        stamp = logic.format_timestamp(datetime.now()) + " "
        insert_pos = block.position() + len(block.text())

        edit_cursor = self.textCursor()
        edit_cursor.beginEditBlock()
        stamp_cursor = QTextCursor(self.document())
        stamp_cursor.setPosition(insert_pos)
        stamp_cursor.insertText(stamp)
        place_cursor = QTextCursor(self.document())
        place_cursor.setPosition(insert_pos + len(stamp))
        self.setTextCursor(place_cursor)
        super().keyPressEvent(event)
        self._apply_hanging_indent(block)
        edit_cursor.endEditBlock()
        return True

    # ------------------------------------------------------------------
    # Enter: carry current indent forward; a second Enter on the still-
    # empty resulting line outdents it one level instead of adding
    # another blank line below (mirrors Shift+Tab/Backspace-outdent, so
    # repeated Enter on an empty line cascades back down to level 0).
    # ------------------------------------------------------------------
    def _handle_enter(self) -> None:
        block = self.textCursor().block()
        level = logic.indent_level(block.text())

        if level > 0 and logic.line_is_empty_of_content(block.text()):
            edit_cursor = self.textCursor()
            edit_cursor.beginEditBlock()
            self._indent_single_line(-1)
            edit_cursor.endEditBlock()
            self.ensureCursorVisible()
            return

        edit_cursor = self.textCursor()
        edit_cursor.beginEditBlock()
        edit_cursor.insertBlock()
        if level > 0:
            edit_cursor.insertText(logic.INDENT_CHAR * level)
        self.setTextCursor(edit_cursor)
        self._apply_hanging_indent(edit_cursor.block())
        self._apply_blank_line_logic(edit_cursor.block())
        edit_cursor.endEditBlock()
        self.ensureCursorVisible()

    # ------------------------------------------------------------------
    # Ctrl+T: insert/refresh timestamp in place
    # ------------------------------------------------------------------
    def _refresh_timestamp(self) -> None:
        cursor = self.textCursor()
        block = cursor.block()
        text = block.text()
        col = cursor.positionInBlock()
        new_stamp = logic.format_timestamp(datetime.now())
        new_text, new_col = logic.apply_timestamp_refresh(text, col, new_stamp)

        edit_cursor = self.textCursor()
        edit_cursor.beginEditBlock()
        line_cursor = QTextCursor(block)
        line_cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        line_cursor.insertText(new_text)
        place_cursor = QTextCursor(self.document())
        place_cursor.setPosition(block.position() + new_col)
        self.setTextCursor(place_cursor)
        self._apply_hanging_indent(block)
        edit_cursor.endEditBlock()

    # ------------------------------------------------------------------
    # Tab / Shift+Tab indent-outdent
    # ------------------------------------------------------------------
    def _indent_selection_or_line(self, delta: int) -> None:
        cursor = self.textCursor()
        edit_cursor = self.textCursor()
        edit_cursor.beginEditBlock()
        if cursor.hasSelection():
            self._indent_multi_line_selection(cursor, delta)
        else:
            self._indent_single_line(delta)
        edit_cursor.endEditBlock()
        self.ensureCursorVisible()

    def _indent_multi_line_selection(self, cursor: QTextCursor, delta: int) -> None:
        # Multi-line selection: indent/outdent every touched line. No
        # auto-blank-line side effect here - that logic is only defined
        # for a single line's transition relative to its immediate
        # predecessor.
        doc = self.document()
        start_block = doc.findBlock(cursor.selectionStart())
        end_block = doc.findBlock(cursor.selectionEnd())
        block = start_block
        while True:
            self._set_block_indent(block, delta)
            if block.blockNumber() == end_block.blockNumber():
                break
            block = block.next()

    def _indent_single_line(self, delta: int) -> None:
        cursor = self.textCursor()
        block = cursor.block()
        saved_col = cursor.positionInBlock()
        if self._set_block_indent(block, delta):
            self._reposition_after_indent_delta(block, saved_col, delta)
        self._apply_blank_line_logic(block)

    def _set_block_indent(self, block: QTextBlock, delta: int) -> bool:
        """Add/remove one leading tab. Returns False (no-op) if outdenting
        a line that's already at level 0."""
        text = block.text()
        if delta > 0:
            new_text = logic.indent_line(text)
        else:
            if logic.indent_level(text) == 0:
                return False
            new_text = logic.outdent_line(text)
        line_cursor = QTextCursor(block)
        line_cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        line_cursor.insertText(new_text)
        self._apply_hanging_indent(block)
        return True

    def _reposition_after_indent_delta(self, block: QTextBlock, saved_col: int, delta: int) -> None:
        # Explicit, rather than relying on Qt's cursor auto-adjustment
        # through a whole-line replace (ambiguous when the cursor sits
        # exactly at the edge of the replaced range).
        new_col = max(0, min(saved_col + delta, len(block.text())))
        place_cursor = QTextCursor(self.document())
        place_cursor.setPosition(block.position() + new_col)
        self.setTextCursor(place_cursor)

    # ------------------------------------------------------------------
    # Backspace-outdent at line start
    # ------------------------------------------------------------------
    def _try_backspace_outdent(self) -> bool:
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False
        block = cursor.block()
        indent_len = logic.indent_prefix_len(block.text())

        if indent_len == 0:
            # At the very start of an unindented line, Qt's default
            # Backspace would merge it into the line above - which can eat
            # a blank-line separator the format invariant requires, or
            # splice two independently-timestamped entries onto one line.
            # Block it there; anywhere else on the line, ordinary
            # character-by-character deletion is unaffected.
            return cursor.positionInBlock() == 0

        # Triggers whenever the cursor sits within/at the end of the
        # leading-tab run (not strictly column 0) - this is where the
        # cursor naturally rests right after pressing Tab, and backspace
        # there is the natural "undo that indent" gesture.
        if cursor.positionInBlock() > indent_len:
            return False

        saved_col = cursor.positionInBlock()
        edit_cursor = self.textCursor()
        edit_cursor.beginEditBlock()
        if self._set_block_indent(block, -1):
            self._reposition_after_indent_delta(block, saved_col, -1)
        self._apply_blank_line_logic(block)
        edit_cursor.endEditBlock()
        self.ensureCursorVisible()
        return True

    # ------------------------------------------------------------------
    # auto blank-line-on-indent-change (shared by Tab/Shift+Tab/Backspace-outdent)
    # ------------------------------------------------------------------
    def _apply_blank_line_logic(self, block: QTextBlock) -> None:
        """Maintain the invariant "a blank line separates two lines only
        when their indent levels differ" on both sides of the line whose
        level just changed - inserting a missing separator or removing one
        that's now redundant, regardless of whether the line has content.

        Takes the target block explicitly rather than reading
        self.textCursor(), so callers never have to reposition the
        widget's actual cursor just to point this at a line - doing that
        mid-edit is what used to cause Qt to scroll the viewport to a
        stray intermediate position (see _move_lines).
        """
        new_level = logic.indent_level(block.text())
        tracker = QTextCursor(block)

        prev = block.previous()
        prev_text = prev.text() if prev.isValid() else None
        prev_prev = prev.previous() if prev.isValid() else None
        prev_prev_text = prev_prev.text() if prev_prev is not None and prev_prev.isValid() else None
        above_action = logic.compute_blank_line_action(new_level, prev_text, prev_prev_text)
        self._apply_blank_action_above(block, above_action)

        # Re-fetch via the tracker: the "above" action may have shifted
        # this line's block number, and a live QTextCursor auto-adjusts
        # across that edit even though it's not the widget's own cursor.
        block = tracker.block()
        nxt = block.next()
        next_text = nxt.text() if nxt.isValid() else None
        next_next = nxt.next() if nxt.isValid() else None
        next_next_text = next_next.text() if next_next is not None and next_next.isValid() else None
        below_action = logic.compute_blank_line_action(new_level, next_text, next_next_text)
        self._apply_blank_action_below(block, below_action)

    def _apply_blank_action_above(self, block: QTextBlock, action: logic.BlankLineAction) -> None:
        if action == logic.BlankLineAction.INSERT:
            insert_cursor = QTextCursor(block)
            insert_cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            insert_cursor.insertBlock()
        elif action == logic.BlankLineAction.REMOVE:
            prev = block.previous()
            remove_cursor = QTextCursor(prev)
            remove_cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            remove_cursor.movePosition(
                QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor
            )
            remove_cursor.removeSelectedText()

    def _apply_blank_action_below(self, block: QTextBlock, action: logic.BlankLineAction) -> None:
        if action == logic.BlankLineAction.INSERT:
            insert_cursor = QTextCursor(block.next())
            insert_cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            insert_cursor.insertBlock()
        elif action == logic.BlankLineAction.REMOVE:
            remove_cursor = QTextCursor(block.next())
            remove_cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            remove_cursor.movePosition(
                QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor
            )
            remove_cursor.removeSelectedText()

    # ------------------------------------------------------------------
    # Alt+Up/Down (move line) and Ctrl+Alt+Up/Down (move line + subtree)
    # ------------------------------------------------------------------
    def _subtree_end(self, first: QTextBlock, base_level: int) -> QTextBlock:
        """Walk forward from `first`, returning the last block in its
        subtree (deeper-level lines). Sees through the blank-line
        separator that normally sits between a parent and its first
        child (or between any two differing levels) - without this, the
        walk would stop at that blank, since a blank's own level (0)
        never exceeds base_level. A blank only continues the subtree if
        something deeper than base_level follows it; otherwise it's the
        subtree's trailing terminator, not part of it.
        """
        last = first
        block = first.next()
        while block.isValid():
            if block.text() == "":
                peek = block
                while peek.isValid() and peek.text() == "":
                    peek = peek.next()
                if peek.isValid() and logic.indent_level(peek.text()) > base_level:
                    block = peek
                    continue
                break
            if logic.indent_level(block.text()) > base_level:
                last = block
                block = block.next()
                continue
            break
        return last

    def _move_lines(self, direction: int, with_subtree: bool) -> None:
        cursor = self.textCursor()
        first = cursor.block()
        saved_col = cursor.positionInBlock()
        base_level = logic.indent_level(first.text())

        last = first
        if with_subtree:
            last = self._subtree_end(first, base_level)

        # The real neighbor to swap with is the next/previous *content*
        # line - skip past any blank separators in between. Those blanks
        # belonged to the old adjacency and are stale once the move
        # happens; they get replaced away below and the invariant is
        # re-run fresh at both new seams, rather than being carried along
        # or left behind as orphaned blank lines.
        if direction < 0:
            neighbor = first.previous()
            while neighbor.isValid() and neighbor.text() == "":
                neighbor = neighbor.previous()
            if not neighbor.isValid():
                return
            span_start_block, span_end_block = neighbor, last
        else:
            neighbor = last.next()
            while neighbor.isValid() and neighbor.text() == "":
                neighbor = neighbor.next()
            if not neighbor.isValid():
                return
            span_start_block, span_end_block = first, neighbor

        moving_texts = []
        b = first
        while True:
            moving_texts.append(b.text())
            if b.blockNumber() == last.blockNumber():
                break
            b = b.next()
        moving_block = "\n".join(moving_texts)

        if direction < 0:
            new_span_text = moving_block + "\n" + neighbor.text()
            user_line_offset_from_head = 0  # first's content lands at the head
        else:
            new_span_text = neighbor.text() + "\n" + moving_block
            user_line_offset_from_head = 1  # first's content lands right after neighbor

        after_span_end = span_end_block.next()
        if after_span_end.isValid():
            end_pos = after_span_end.position() - 1
        else:
            end_pos = span_end_block.position() + len(span_end_block.text())

        select_cursor = QTextCursor(span_start_block)
        select_cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        select_cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)

        span_start_pos = span_start_block.position()

        edit_cursor = self.textCursor()
        edit_cursor.beginEditBlock()
        select_cursor.insertText(new_span_text)

        # The replaced region always has len(moving_texts) + 1 blocks
        # (the moving lines plus neighbor), regardless of direction or
        # which chunk landed first. Track the region's head/tail blocks -
        # the two new seams created by the swap - and `first`'s own new
        # line (for restoring the cursor), all via live QTextCursor
        # instances captured now so they auto-adjust through the
        # blank-line fixes below.
        head_block = self.document().findBlock(span_start_pos)
        tail_block = head_block
        for _ in range(len(moving_texts)):
            tail_block = tail_block.next()
        user_line_block = head_block
        for _ in range(user_line_offset_from_head):
            user_line_block = user_line_block.next()

        tail_tracker = QTextCursor(tail_block)
        user_line_tracker = QTextCursor(user_line_block)
        user_line_tracker.setPosition(
            user_line_block.position() + min(saved_col, len(user_line_block.text()))
        )

        # Fix up the blank-line invariant at both new seams without ever
        # repositioning the widget's own cursor mid-edit - doing that via
        # setTextCursor here used to make Qt scroll the viewport to a
        # stray intermediate position before the move had even finished.
        self._apply_blank_line_logic(head_block)
        self._apply_blank_line_logic(tail_tracker.block())

        # Formats aren't reliably preserved across a bulk text replace -
        # reformat every block in the final (post-blank-fix) region.
        b = self.document().findBlock(span_start_pos)
        final_tail = tail_tracker.block()
        while True:
            self._apply_hanging_indent(b)
            if b.blockNumber() == final_tail.blockNumber():
                break
            b = b.next()

        edit_cursor.endEditBlock()

        self.setTextCursor(user_line_tracker)
        self.ensureCursorVisible()

"""Manage Marks dialog (PR 14c).

A modal dialog surfacing every pending redaction group across the
document. Users can review, edit, reset, or remove groups either one
at a time or in bulk via checkbox multi-select.

The dialog owns its mutations: it accepts a ``RedactionService`` and
session defaults at construction, calls the service directly, and emits
a ``changed`` signal after each successful mutation. DocumentView
listens on ``changed`` to refresh page cache and rebind panels.

Table columns: checkbox | text | marks count | pages | status | actions.
Row actions: Edit (opens EditGroupDialog scoped to the group), Reset
(applies current session defaults; enabled only for Custom groups),
Remove (with confirmation dialog).

Bulk buttons (act on checked rows): Select All / Select None (no
confirmation), Edit Selected (opens EditGroupDialog; values overwrite
all selected), Reset Selected (applies session defaults to selected
Custom groups; Global rows skipped), Remove Selected (with
confirmation).

Close button dismisses without prompt; mutations already applied.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pdfprism.services.redaction import RedactionService
from pdfprism.ui.dialogs.edit_group import EditGroupDialog


class ManageMarksDialog(QDialog):
    """Grouped review UI for pending redaction marks."""

    # Emitted after any successful mutation (edit, reset, remove) so
    # the caller can refresh panels / cache. Payload: count of mutations
    # in this operation (row-level = 1; bulk = N).
    changed = Signal(int)

    def __init__(
        self,
        *,
        service: RedactionService,
        session_fill: tuple[int, int, int],
        session_text: str | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Pending Redaction Marks")
        self.setModal(True)
        self.resize(760, 480)

        self._service = service
        self._session_fill = session_fill
        self._session_text = session_text
        self._groups: list = []

        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Table
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["", "Text", "Marks", "Pages", "Status", "Actions"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self._table)

        # Footer count label
        self._footer = QLabel("")
        root.addWidget(self._footer)

        # Bulk buttons row
        bulk_row = QHBoxLayout()
        self._select_all_button = QPushButton("Select All")
        self._select_none_button = QPushButton("Select None")
        self._edit_selected_button = QPushButton("Edit Selected")
        self._reset_selected_button = QPushButton("Reset Selected")
        self._remove_selected_button = QPushButton("Remove Selected")
        bulk_row.addWidget(self._select_all_button)
        bulk_row.addWidget(self._select_none_button)
        bulk_row.addStretch()
        bulk_row.addWidget(self._edit_selected_button)
        bulk_row.addWidget(self._reset_selected_button)
        bulk_row.addWidget(self._remove_selected_button)
        root.addLayout(bulk_row)

        # Wire bulk actions
        self._select_all_button.clicked.connect(self._on_select_all)
        self._select_none_button.clicked.connect(self._on_select_none)
        self._edit_selected_button.clicked.connect(self._on_edit_selected)
        self._reset_selected_button.clicked.connect(self._on_reset_selected)
        self._remove_selected_button.clicked.connect(self._on_remove_selected)

        # PR 14c: update bulk button enabled state whenever a
        # row's checkbox toggles.
        self._table.itemChanged.connect(self._on_item_changed)

        # Close button
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _populate(self) -> None:
        """PR 14c: fetch groups from the service and fill the table.

        Query is done fresh on every populate call -- called after
        every mutation so the display always reflects current state.
        Checkbox state is not preserved across populate calls (any
        mutation that changes the row set invalidates the selection).
        """
        try:
            self._groups = self._service.list_redactions_grouped(
                session_fill=self._session_fill,
                session_text=self._session_text,
            )
        except Exception:
            self._groups = []

        self._table.setRowCount(len(self._groups))

        for row, group in enumerate(self._groups):
            # Column 0: checkbox
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check_item.setCheckState(Qt.CheckState.Unchecked)
            self._table.setItem(row, 0, check_item)

            # Column 1: display text
            self._table.setItem(row, 1, QTableWidgetItem(group.text))

            # Column 2: mark count
            count_item = QTableWidgetItem(str(group.count))
            self._table.setItem(row, 2, count_item)

            # Column 3: pages (1-based for display)
            pages_display = ",".join(str(pi + 1) for pi in group.page_indices)
            self._table.setItem(row, 3, QTableWidgetItem(pages_display))

            # Column 4: status
            status_label = "🔵 Custom" if group.is_customized else "🟢 Global"
            self._table.setItem(row, 4, QTableWidgetItem(status_label))

            # Column 5: actions (Edit; Reset + Remove wired in later sub-steps)
            actions_widget = self._build_actions_cell(row)
            self._table.setCellWidget(row, 5, actions_widget)

        # Column sizing
        self._table.resizeColumnsToContents()

        # Footer count
        total_marks = sum(g.count for g in self._groups)
        group_count = len(self._groups)
        if group_count == 0:
            self._footer.setText("(no pending marks)")
        else:
            self._footer.setText(f"{total_marks} pending mark(s) across {group_count} group(s)")
        # PR 14c: refresh bulk buttons after populate (new row set may
        # invalidate previously-checked state; enable state must reflect
        # current selection)
        self._refresh_bulk_buttons()

    def _build_actions_cell(self, row: int) -> QWidget:
        """Build a per-row cell widget hosting the row action buttons.

        This sub-step wires the Edit button; Reset (sub-step 5) and
        Remove (sub-step 6) fill in as later PRs of this milestone.
        """
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        edit_btn = QPushButton("Edit")
        # Capture row index at binding time (default-arg trick avoids
        # late-binding closure over the loop variable).
        edit_btn.clicked.connect(lambda _=False, r=row: self._on_edit_row(r))
        layout.addWidget(edit_btn)

        reset_btn = QPushButton("Reset")
        # Reset is a no-op for Global groups (nothing to reset);
        # disable to communicate that visually and prevent
        # accidental redundant calls.
        reset_btn.setEnabled(self._groups[row].is_customized)
        reset_btn.clicked.connect(lambda _=False, r=row: self._on_reset_row(r))
        layout.addWidget(reset_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(lambda _=False, r=row: self._on_remove_row(r))
        layout.addWidget(remove_btn)

        layout.addStretch()
        return container

    def _on_edit_row(self, row: int) -> None:
        """Open EditGroupDialog for the given row's group and apply on OK.

        Idempotent against a stale row index: if the row's group has
        been mutated since populate (unlikely in single-threaded UI but
        safe), the dialog still targets the current in-memory group.
        """
        if not (0 <= row < len(self._groups)):
            return
        group = self._groups[row]
        # Prefill with first mark's values -- group is atomic so all
        # marks share styling by design.
        first = group.marks[0]
        dlg = EditGroupDialog(
            group_display_text=group.text,
            group_size=group.count,
            is_customized=group.is_customized,
            current_fill=first.fill_color,
            current_text=first.replacement_text,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # Determine the values to apply
        if dlg.was_reset:
            new_fill = self._session_fill
            new_text = self._session_text
        else:
            new_fill = dlg.fill_color
            new_text = dlg.replacement_text
        try:
            count = self._service.update_redaction_group(group.normalized_text, new_fill, new_text)
        except Exception:
            return
        if count > 0:
            self.changed.emit(count)
        self._populate()

    def _on_reset_row(self, row: int) -> None:
        """Apply session defaults to the row's group.

        Reset is not destructive -- values can be re-edited afterward
        -- so no confirmation dialog. Global rows have this button
        disabled at build time, but defense-in-depth check inside
        this handler tolerates that being bypassed programmatically.
        """
        if not (0 <= row < len(self._groups)):
            return
        group = self._groups[row]
        if not group.is_customized:
            return  # nothing to reset
        try:
            count = self._service.update_redaction_group(
                group.normalized_text,
                self._session_fill,
                self._session_text,
            )
        except Exception:
            return
        if count > 0:
            self.changed.emit(count)
        self._populate()

    def _on_remove_row(self, row: int) -> None:
        """Remove the row's group after confirmation.

        Destructive: confirmation dialog required. Message adapts to
        group size ("Remove 'X' group (N marks)?" for multi, "Remove
        'X' mark?" for singleton). Cancel is the default focused
        button to guard against accidental confirms.
        """
        if not (0 <= row < len(self._groups)):
            return
        group = self._groups[row]
        if group.count == 1:
            question = f'Remove "{group.text}" mark?'
        else:
            question = f'Remove "{group.text}" group ({group.count} marks)?'
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Remove Redaction Mark")
        msg.setText(question)
        msg.setInformativeText("This action cannot be undone.")
        remove_button = msg.addButton("Remove", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = msg.addButton(QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(cancel_button)
        msg.exec()
        if msg.clickedButton() is not remove_button:
            return
        try:
            count = self._service.remove_redaction_group(group.normalized_text)
        except Exception:
            return
        if count > 0:
            self.changed.emit(count)
        self._populate()

    # ---- Bulk operations -----------------------------------------

    def _checked_rows(self) -> list[int]:
        """Return indices of rows whose checkbox is currently checked."""
        rows: list[int] = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                rows.append(row)
        return rows

    def _set_all_checked(self, checked: bool) -> None:
        """Set every row's checkbox to the given state."""
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is not None:
                item.setCheckState(state)

    def _on_select_all(self) -> None:
        self._set_all_checked(True)

    def _on_select_none(self) -> None:
        self._set_all_checked(False)

    def _on_edit_selected(self) -> None:
        """Open EditGroupDialog once; applied values overwrite every
        selected group's fill/text.

        The dialog is prefilled with the first selected group's values
        as a starting point; users may change them freely. Group
        atomicity is preserved -- each affected group's marks end up
        with matching styling after the operation.
        """
        rows = self._checked_rows()
        if not rows:
            return
        selected_groups = [self._groups[r] for r in rows]
        total_marks = sum(g.count for g in selected_groups)
        header = f"Editing {len(selected_groups)} group(s) ({total_marks} mark(s) total)"

        # Prefill with the first selected group's first mark for
        # convenience.
        first_group = selected_groups[0]
        first_mark = first_group.marks[0]
        dlg = EditGroupDialog(
            group_display_text=header,
            group_size=total_marks,
            is_customized=any(g.is_customized for g in selected_groups),
            current_fill=first_mark.fill_color,
            current_text=first_mark.replacement_text,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.was_reset:
            new_fill = self._session_fill
            new_text = self._session_text
        else:
            new_fill = dlg.fill_color
            new_text = dlg.replacement_text

        total_updated = 0
        for group in selected_groups:
            try:
                count = self._service.update_redaction_group(
                    group.normalized_text, new_fill, new_text
                )
                total_updated += count
            except Exception:
                # Skip that group; others still apply.
                continue
        if total_updated > 0:
            self.changed.emit(total_updated)
        self._populate()

    def _on_reset_selected(self) -> None:
        """Apply session defaults to every checked Custom group.

        Global groups in the selection are silently skipped (nothing
        to reset). No confirmation dialog -- Reset is non-destructive.
        """
        rows = self._checked_rows()
        if not rows:
            return
        total_updated = 0
        for row in rows:
            group = self._groups[row]
            if not group.is_customized:
                continue
            try:
                count = self._service.update_redaction_group(
                    group.normalized_text,
                    self._session_fill,
                    self._session_text,
                )
                total_updated += count
            except Exception:
                continue
        if total_updated > 0:
            self.changed.emit(total_updated)
        self._populate()

    def _on_remove_selected(self) -> None:
        """Remove every checked group after single confirmation.

        Confirmation dialog shows total counts across the selection
        ("Remove N groups (M marks)?"). Cancel is the default focused
        button.
        """
        rows = self._checked_rows()
        if not rows:
            return
        selected_groups = [self._groups[r] for r in rows]
        total_marks = sum(g.count for g in selected_groups)
        group_count = len(selected_groups)

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Remove Redaction Marks")
        if group_count == 1:
            msg.setText(f"Remove {group_count} group ({total_marks} mark(s))?")
        else:
            msg.setText(f"Remove {group_count} groups ({total_marks} marks total)?")
        msg.setInformativeText("This action cannot be undone.")
        remove_button = msg.addButton("Remove", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = msg.addButton(QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(cancel_button)
        msg.exec()
        if msg.clickedButton() is not remove_button:
            return

        total_removed = 0
        for group in selected_groups:
            try:
                count = self._service.remove_redaction_group(group.normalized_text)
                total_removed += count
            except Exception:
                continue
        if total_removed > 0:
            self.changed.emit(total_removed)
        self._populate()

    def _refresh_bulk_buttons(self) -> None:
        """PR 14c: enable/disable bulk buttons based on current selection.

        - Edit Selected: enabled iff any row is checked
        - Reset Selected: enabled iff any checked row is Custom
          (Global rows are silently skipped by the handler; if none
          are Custom, the whole action is a no-op)
        - Remove Selected: enabled iff any row is checked
        """
        rows = self._checked_rows()
        has_any = bool(rows)
        has_customized = any(
            self._groups[r].is_customized for r in rows if 0 <= r < len(self._groups)
        )
        self._edit_selected_button.setEnabled(has_any)
        self._reset_selected_button.setEnabled(has_any and has_customized)
        self._remove_selected_button.setEnabled(has_any)

    def _on_item_changed(self, _item) -> None:
        """PR 14c: refresh bulk buttons when a checkbox state changes.

        Uses ``QTableWidget.itemChanged`` which fires for any cell edit
        including check state toggles. Only checkbox items (column 0)
        would meaningfully affect bulk button state, but refreshing on
        all changes is cheap and covers edge cases.
        """
        self._refresh_bulk_buttons()

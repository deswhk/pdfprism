"""Merge dialog: combine open tabs into a single PDF.

The dialog lists every open tab with a checkbox; the user un-checks
any to exclude, and uses Up/Down buttons to reorder. Output is a new
PDF file path.

The dialog operates on *indices* — it knows nothing about adapters or
DocumentView. The caller passes ``tab_titles`` (in tab order) and
reads ``selected_tab_indices`` after Accepted to know which adapters
to pass to ``services.pages.merge`` and in what order.

OK is enabled only when at least two items are checked and an output
path is set; this enforces the "merge requires >= 2 sources" rule at
the UI level so the service-level error never reaches the user.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class MergeDialog(QDialog):
    """Modal dialog: tab selection + ordering + output path."""

    def __init__(
        self,
        tab_titles: list[str],
        default_output_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Merge Documents")

        # ---- Tab list -------------------------------------------------------
        self._list = QListWidget()
        for i, title in enumerate(tab_titles):
            item = QListWidgetItem(title)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            # Stash the original tab index so reorder doesn't lose it.
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._list.addItem(item)
        self._list.itemChanged.connect(self._refresh_ok_state)

        # ---- Up / Down buttons ----------------------------------------------
        up_btn = QPushButton("Move Up")
        up_btn.clicked.connect(self._move_up)
        down_btn = QPushButton("Move Down")
        down_btn.clicked.connect(self._move_down)

        order_col = QVBoxLayout()
        order_col.addWidget(up_btn)
        order_col.addWidget(down_btn)
        order_col.addStretch(1)

        list_row = QHBoxLayout()
        list_row.addWidget(self._list, 1)
        list_row.addLayout(order_col)

        # ---- Output path ----------------------------------------------------
        self._output_edit = QLineEdit(str(default_output_path))
        self._output_edit.textChanged.connect(self._refresh_ok_state)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_output)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Save as:"))
        out_row.addWidget(self._output_edit, 1)
        out_row.addWidget(browse_btn)

        # ---- Buttons --------------------------------------------------------
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)

        # ---- Layout ---------------------------------------------------------
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Choose which open documents to merge, and in what order.\n"
                "Unsaved changes in source documents will be included."
            )
        )
        layout.addLayout(list_row, 1)
        layout.addLayout(out_row)
        layout.addWidget(self._button_box)

        self._refresh_ok_state()

    # ---- Reorder helpers -----------------------------------------------------

    def _move_up(self) -> None:
        row = self._list.currentRow()
        if row <= 0:
            return
        item = self._list.takeItem(row)
        self._list.insertItem(row - 1, item)
        self._list.setCurrentRow(row - 1)

    def _move_down(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= self._list.count() - 1:
            return
        item = self._list.takeItem(row)
        self._list.insertItem(row + 1, item)
        self._list.setCurrentRow(row + 1)

    # ---- Output path ---------------------------------------------------------

    def _browse_output(self) -> None:
        suggestion = self._output_edit.text()
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Save Merged PDF",
            suggestion,
            "PDF files (*.pdf);;All files (*)",
        )
        if chosen:
            self._output_edit.setText(chosen)

    # ---- OK button state -----------------------------------------------------

    def _checked_count(self) -> int:
        count = 0
        for i in range(self._list.count()):
            if self._list.item(i).checkState() == Qt.CheckState.Checked:
                count += 1
        return count

    def _refresh_ok_state(self) -> None:
        ok = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok is None:
            return
        ok.setEnabled(self._checked_count() >= 2 and bool(self._output_edit.text().strip()))

    # ---- Public properties ---------------------------------------------------

    @property
    def selected_tab_indices(self) -> list[int]:
        """Original tab indices of checked items, in the dialog's order."""
        out: list[int] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    @property
    def output_path(self) -> Path:
        return Path(self._output_edit.text().strip())

"""Combine dialog (PR 16).

Multi-source PDF list picker for the "File -> Combine PDFs..." flow.
The user builds an ordered list of source PDFs via Add / Remove /
Move Up / Move Down (or drag-reorder). Order matters: for pending
redaction group style collisions across sources, the last source
wins (see M5 architecture Q&A for design rationale).

The dialog is dumb: it does not touch the adapter, service, or
filesystem. Caller reads ``sources`` after ``exec`` returns
Accepted and drives the actual combine.
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
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class CombineDialog(QDialog):
    """Ordered list picker for source PDFs to combine."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Combine PDFs")
        self.setModal(True)
        self.resize(560, 420)

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        root.addWidget(QLabel("Sources (drag to reorder):"))

        # QListWidget with internal drag-and-drop for reordering
        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.model().rowsMoved.connect(self._refresh_buttons)
        self._list.currentRowChanged.connect(self._refresh_buttons)
        root.addWidget(self._list)

        # Add / Move / Remove row
        controls_row = QHBoxLayout()
        self._add_button = QPushButton("Add PDF...")
        self._add_button.clicked.connect(self._on_add)
        controls_row.addWidget(self._add_button)
        controls_row.addStretch()

        self._move_up_button = QPushButton("Move Up")
        self._move_up_button.clicked.connect(self._on_move_up)
        controls_row.addWidget(self._move_up_button)

        self._move_down_button = QPushButton("Move Down")
        self._move_down_button.clicked.connect(self._on_move_down)
        controls_row.addWidget(self._move_down_button)

        self._remove_button = QPushButton("Remove")
        self._remove_button.clicked.connect(self._on_remove)
        controls_row.addWidget(self._remove_button)

        root.addLayout(controls_row)

        # Info label
        info = QLabel(
            "Order controls priority for redaction style reconciliation: "
            "the last source wins on style collisions."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: gray; font-size: 10px;")
        root.addWidget(info)

        # OK / Cancel buttons
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._combine_button = QPushButton("Combine")
        self._combine_button.setDefault(True)
        self._buttons.addButton(self._combine_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self._combine_button.clicked.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

        self._refresh_buttons()

    def _refresh_buttons(self, *args) -> None:
        """Enable buttons based on current list state and selection."""
        count = self._list.count()
        current_row = self._list.currentRow()

        self._combine_button.setEnabled(count >= 2)
        has_selection = current_row >= 0 and count > 0
        self._remove_button.setEnabled(has_selection)
        self._move_up_button.setEnabled(has_selection and current_row > 0)
        self._move_down_button.setEnabled(has_selection and current_row < count - 1)

    def _on_add(self) -> None:
        """Open file picker to add one or more PDFs to the list."""
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add PDFs to Combine",
            "",
            "PDF files (*.pdf);;All files (*)",
        )
        if not paths:
            return
        for path_str in paths:
            path = Path(path_str)
            # Display just the name; store the full path in item data.
            from PySide6.QtWidgets import QListWidgetItem

            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self._list.addItem(item)
        self._refresh_buttons()

    def _on_remove(self) -> None:
        """Remove the currently selected row."""
        row = self._list.currentRow()
        if row < 0:
            return
        self._list.takeItem(row)
        self._refresh_buttons()

    def _on_move_up(self) -> None:
        row = self._list.currentRow()
        if row <= 0:
            return
        item = self._list.takeItem(row)
        self._list.insertItem(row - 1, item)
        self._list.setCurrentRow(row - 1)
        self._refresh_buttons()

    def _on_move_down(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= self._list.count() - 1:
            return
        item = self._list.takeItem(row)
        self._list.insertItem(row + 1, item)
        self._list.setCurrentRow(row + 1)
        self._refresh_buttons()

    # ---- Public accessors ----

    @property
    def sources(self) -> list[Path]:
        """Return ordered list of source paths in the list."""
        result: list[Path] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            path_str = item.data(Qt.ItemDataRole.UserRole)
            if path_str:
                result.append(Path(path_str))
        return result

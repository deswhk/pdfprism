"""Compare dialog (PR 17a).

Small dialog for the "File -> Compare PDFs..." flow. The user picks
two documents to compare: each can be an already-open tab or an
external file browsed via QFileDialog.

The dialog is dumb: it takes a list of currently-open tab paths at
construction, does not touch the adapter/service/filesystem, and
exposes ``left_path`` and ``right_path`` as accessors after the user
accepts.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class CompareDialog(QDialog):
    """Two-document picker for the compare flow.

    Args:
        parent: parent widget (typically MainWindow)
        open_tab_paths: paths of currently-open tabs; user can pick
            from these directly, or select "(external file...)" and
            browse.
        default_left_path: if set, pre-select this path on the left
            side (typically the active tab).
    """

    EXTERNAL_LABEL = "(external file...)"

    def __init__(
        self,
        parent: QWidget | None = None,
        open_tab_paths: list[Path] | None = None,
        default_left_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compare PDFs")
        self.setModal(True)
        self.resize(520, 220)

        self._open_paths: list[Path] = list(open_tab_paths or [])
        self._external_left: Path | None = None
        self._external_right: Path | None = None

        self._build_ui()
        self._populate_combos()

        # Pre-select default_left_path if provided and in open tabs
        if default_left_path is not None:
            for i, path in enumerate(self._open_paths):
                if path == default_left_path:
                    self._left_combo.setCurrentIndex(i)
                    break

        self._on_selection_changed()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Left document row
        root.addWidget(QLabel("Left document:"))
        left_row = QHBoxLayout()
        self._left_combo = QComboBox()
        self._left_combo.setMinimumWidth(320)
        self._left_combo.currentIndexChanged.connect(self._on_selection_changed)
        left_row.addWidget(self._left_combo, stretch=1)
        self._left_browse = QPushButton("Browse...")
        self._left_browse.clicked.connect(self._on_left_browse)
        left_row.addWidget(self._left_browse)
        root.addLayout(left_row)
        self._left_path_label = QLabel("(no file selected)")
        self._left_path_label.setStyleSheet("color: gray; font-size: 10px;")
        root.addWidget(self._left_path_label)

        root.addSpacing(10)

        # Right document row
        root.addWidget(QLabel("Right document:"))
        right_row = QHBoxLayout()
        self._right_combo = QComboBox()
        self._right_combo.setMinimumWidth(320)
        self._right_combo.currentIndexChanged.connect(self._on_selection_changed)
        right_row.addWidget(self._right_combo, stretch=1)
        self._right_browse = QPushButton("Browse...")
        self._right_browse.clicked.connect(self._on_right_browse)
        right_row.addWidget(self._right_browse)
        root.addLayout(right_row)
        self._right_path_label = QLabel("(no file selected)")
        self._right_path_label.setStyleSheet("color: gray; font-size: 10px;")
        root.addWidget(self._right_path_label)

        root.addStretch()

        # OK/Cancel buttons
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._compare_button = QPushButton("Compare")
        self._compare_button.setDefault(True)
        self._buttons.addButton(self._compare_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self._compare_button.clicked.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

    def _populate_combos(self) -> None:
        """Fill both combos with open tab entries + external option."""
        for combo in (self._left_combo, self._right_combo):
            combo.blockSignals(True)
            combo.clear()
            for path in self._open_paths:
                combo.addItem(path.name, userData=str(path))
            combo.addItem(self.EXTERNAL_LABEL, userData=None)
            combo.blockSignals(False)

    def _resolve_path(self, combo: QComboBox, external: Path | None) -> Path | None:
        """Return the currently-selected path for a combo."""
        if combo.currentText() == self.EXTERNAL_LABEL:
            return external
        # Value stored as string path
        value = combo.currentData()
        if isinstance(value, str):
            return Path(value)
        return None

    def _on_selection_changed(self, *args) -> None:
        """Update path labels and Compare button enable state."""
        left_path = self._resolve_path(self._left_combo, self._external_left)
        right_path = self._resolve_path(self._right_combo, self._external_right)

        self._left_path_label.setText(str(left_path) if left_path else "(no file selected)")
        self._right_path_label.setText(str(right_path) if right_path else "(no file selected)")

        # Compare enabled only when both paths resolved and different
        both_present = left_path is not None and right_path is not None
        different = left_path != right_path if both_present else False
        self._compare_button.setEnabled(both_present and different)

    def _on_left_browse(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Select left document",
            "",
            "PDF files (*.pdf);;All files (*)",
        )
        if path_str:
            self._external_left = Path(path_str)
            # Switch combo to the external option
            index = self._left_combo.findText(self.EXTERNAL_LABEL)
            if index >= 0:
                self._left_combo.setCurrentIndex(index)
            self._on_selection_changed()

    def _on_right_browse(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Select right document",
            "",
            "PDF files (*.pdf);;All files (*)",
        )
        if path_str:
            self._external_right = Path(path_str)
            index = self._right_combo.findText(self.EXTERNAL_LABEL)
            if index >= 0:
                self._right_combo.setCurrentIndex(index)
            self._on_selection_changed()

    # ---- Public accessors ----

    @property
    def left_path(self) -> Path | None:
        return self._resolve_path(self._left_combo, self._external_left)

    @property
    def right_path(self) -> Path | None:
        return self._resolve_path(self._right_combo, self._external_right)

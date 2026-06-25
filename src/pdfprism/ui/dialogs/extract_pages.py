"""Extract Pages to File dialog.

Pick a page range from the current document and an output path; the
service writes those pages as a new PDF. Source document is unchanged.

The range is 1-based in the UI (matching the page navigator) but the
``page_range`` property returns the 0-based inclusive ``(from_idx,
to_idx)`` tuple that the adapter contract expects.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class ExtractPagesDialog(QDialog):
    """Modal dialog: pick a page range and an output path."""

    def __init__(
        self,
        source_path: Path,
        page_count: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extract Pages to File")
        self._source_path = source_path
        self._page_count = page_count

        # ---- Page range -----------------------------------------------------
        self._from_spin = QSpinBox()
        self._from_spin.setRange(1, page_count)
        self._from_spin.setValue(1)
        self._to_spin = QSpinBox()
        self._to_spin.setRange(1, page_count)
        self._to_spin.setValue(page_count)
        # Keep from <= to as the user adjusts the spinboxes.
        self._from_spin.valueChanged.connect(self._sync_to_min)
        self._to_spin.valueChanged.connect(self._sync_from_max)

        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Pages from"))
        range_row.addWidget(self._from_spin)
        range_row.addWidget(QLabel("to"))
        range_row.addWidget(self._to_spin)
        range_row.addStretch(1)

        # ---- Output path ----------------------------------------------------
        self._output_edit = QLineEdit()
        self._output_edit.setText(str(self._default_output_path()))
        self._output_edit.textChanged.connect(self._refresh_ok_state)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_output)

        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Save as:"))
        output_row.addWidget(self._output_edit, 1)
        output_row.addWidget(browse_btn)

        # ---- Buttons --------------------------------------------------------
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"Source: {source_path.name} ({page_count} page{'s' if page_count != 1 else ''})"
            )
        )
        layout.addLayout(range_row)
        layout.addLayout(output_row)
        layout.addWidget(self._button_box)

        self._refresh_ok_state()

    # ---- Spinbox sync ---------------------------------------------------------

    def _sync_to_min(self, value: int) -> None:
        if self._to_spin.value() < value:
            self._to_spin.setValue(value)

    def _sync_from_max(self, value: int) -> None:
        if self._from_spin.value() > value:
            self._from_spin.setValue(value)

    # ---- Output path helpers --------------------------------------------------

    def _default_output_path(self) -> Path:
        stem = self._source_path.stem
        return self._source_path.with_name(f"{stem}_pages.pdf")

    def _browse_output(self) -> None:
        suggestion = self._output_edit.text() or str(self._default_output_path())
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Save Extracted Pages",
            suggestion,
            "PDF files (*.pdf);;All files (*)",
        )
        if chosen:
            self._output_edit.setText(chosen)

    def _refresh_ok_state(self) -> None:
        ok = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setEnabled(bool(self._output_edit.text().strip()))

    # ---- Public properties ----------------------------------------------------

    @property
    def page_range(self) -> tuple[int, int]:
        """Return 0-based inclusive ``(from_idx, to_idx)``."""
        return (self._from_spin.value() - 1, self._to_spin.value() - 1)

    @property
    def output_path(self) -> Path:
        return Path(self._output_edit.text().strip())

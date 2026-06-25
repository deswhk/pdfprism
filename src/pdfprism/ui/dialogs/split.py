"""Split dialog: break the current document into multiple PDFs.

Two modes:

- **Every N pages** — produces ``ceil(page_count / N)`` files, each
  containing at most N consecutive pages. (N=1 gives one PDF per page.)
- **At pages** — comma-separated 1-based breakpoints; a new file
  begins at each listed page.

Output files are named ``<source-stem>-<i>.pdf`` (1-based, zero-padded
to the digit width of the largest index), written to a user-chosen
directory.

Validation runs on OK: invalid input shows an error and keeps the
dialog open; the calling slot only sees breakpoints when the user
explicitly accepts a valid configuration.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class SplitDialog(QDialog):
    """Modal dialog: split mode + output directory."""

    def __init__(
        self,
        source_path: Path,
        page_count: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Split Document")
        self._page_count = page_count
        self._source_path = source_path
        self._computed_breakpoints: list[int] = []

        # ---- Mode radios ----------------------------------------------------
        self._every_radio = QRadioButton("Every")
        self._every_radio.setChecked(True)
        self._at_radio = QRadioButton("At pages:")
        group = QButtonGroup(self)
        group.addButton(self._every_radio)
        group.addButton(self._at_radio)

        self._every_spin = QSpinBox()
        self._every_spin.setRange(1, max(page_count, 1))
        self._every_spin.setValue(min(2, max(page_count, 1)))

        every_row = QHBoxLayout()
        every_row.addWidget(self._every_radio)
        every_row.addWidget(self._every_spin)
        every_row.addWidget(QLabel(f"pages (document has {page_count} pages)"))
        every_row.addStretch(1)

        self._at_edit = QLineEdit()
        self._at_edit.setPlaceholderText("e.g. 5, 10, 15")
        self._at_edit.textChanged.connect(self._activate_at_mode)

        at_row = QHBoxLayout()
        at_row.addWidget(self._at_radio)
        at_row.addWidget(self._at_edit, 1)

        # ---- Output dir -----------------------------------------------------
        self._dir_edit = QLineEdit(str(source_path.parent))
        self._dir_edit.textChanged.connect(self._refresh_ok_state)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_dir)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Output folder:"))
        dir_row.addWidget(self._dir_edit, 1)
        dir_row.addWidget(browse_btn)

        # ---- Buttons --------------------------------------------------------
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.accepted.connect(self._on_accept)
        self._button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Source: {source_path.name}"))
        layout.addLayout(every_row)
        layout.addLayout(at_row)
        layout.addLayout(dir_row)
        layout.addWidget(self._button_box)

        self._refresh_ok_state()

    # ---- UI plumbing ---------------------------------------------------------

    def _activate_at_mode(self, _text: str) -> None:
        """Selecting the 'At pages' input flips the mode radio."""
        if self._at_edit.text().strip():
            self._at_radio.setChecked(True)

    def _browse_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", self._dir_edit.text()
        )
        if chosen:
            self._dir_edit.setText(chosen)

    def _refresh_ok_state(self) -> None:
        ok = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setEnabled(bool(self._dir_edit.text().strip()))

    # ---- Validation + accept -------------------------------------------------

    def _parse_at_pages(self) -> list[int] | None:
        """Return 0-based breakpoints, or None on invalid input."""
        raw = self._at_edit.text().strip()
        if not raw:
            QMessageBox.warning(self, "Split", "Enter at least one page number.")
            return None
        try:
            ones_based = [int(tok.strip()) for tok in raw.split(",") if tok.strip()]
        except ValueError:
            QMessageBox.warning(self, "Split", "Page numbers must be integers separated by commas.")
            return None
        out_of_range = [n for n in ones_based if not 1 < n <= self._page_count]
        if out_of_range:
            QMessageBox.warning(
                self,
                "Split",
                f"Out-of-range page numbers: {out_of_range}. "
                f"Valid range is 2 to {self._page_count}.",
            )
            return None
        # Convert to 0-based and dedupe.
        return sorted({n - 1 for n in ones_based})

    def _every_n_breakpoints(self) -> list[int]:
        n = self._every_spin.value()
        return [i for i in range(n, self._page_count, n)]

    def _on_accept(self) -> None:
        if self._every_radio.isChecked():
            self._computed_breakpoints = self._every_n_breakpoints()
        else:
            parsed = self._parse_at_pages()
            if parsed is None:
                return  # stay open
            self._computed_breakpoints = parsed
        self.accept()

    # ---- Public properties ---------------------------------------------------

    @property
    def breakpoints(self) -> list[int]:
        """0-based slice-start indices, ready for ``PageService.split``."""
        return list(self._computed_breakpoints)

    @property
    def output_dir(self) -> Path:
        return Path(self._dir_edit.text().strip())

    @property
    def stem(self) -> str:
        return self._source_path.stem

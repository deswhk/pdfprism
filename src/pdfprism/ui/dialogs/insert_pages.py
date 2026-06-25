"""Insert Pages from File dialog.

Choose a page range from a source PDF and the target position in the
currently open document. The source file is picked separately (before
this dialog opens) by the caller, who passes the path and page count
in.

UI is 1-based; ``source_range`` returns 0-based inclusive
``(from_idx, to_idx)`` and ``target_position`` returns the 0-based
insertion index that the adapter's ``insert_pdf`` expects (0 prepends,
target_page_count appends).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class InsertPagesDialog(QDialog):
    """Modal dialog: source range + target insertion position."""

    def __init__(
        self,
        source_path: Path,
        source_page_count: int,
        target_name: str,
        target_page_count: int,
        default_target_position: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Insert Pages from File")
        self._source_page_count = source_page_count
        self._target_page_count = target_page_count

        # ---- Source range ---------------------------------------------------
        self._from_spin = QSpinBox()
        self._from_spin.setRange(1, source_page_count)
        self._from_spin.setValue(1)
        self._to_spin = QSpinBox()
        self._to_spin.setRange(1, source_page_count)
        self._to_spin.setValue(source_page_count)
        self._from_spin.valueChanged.connect(self._sync_to_min)
        self._to_spin.valueChanged.connect(self._sync_from_max)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("From source pages"))
        source_row.addWidget(self._from_spin)
        source_row.addWidget(QLabel("to"))
        source_row.addWidget(self._to_spin)
        source_row.addStretch(1)

        # ---- Target position ------------------------------------------------
        # Insert *before* page N. N in [1, target_page_count + 1]; the
        # upper bound represents "append at end".
        self._position_spin = QSpinBox()
        self._position_spin.setRange(1, target_page_count + 1)
        self._position_spin.setValue(max(1, min(default_target_position, target_page_count + 1)))

        position_row = QHBoxLayout()
        position_row.addWidget(QLabel("Insert before page"))
        position_row.addWidget(self._position_spin)
        position_row.addWidget(
            QLabel(
                f"of {target_name} ({target_page_count} page"
                f"{'s' if target_page_count != 1 else ''}; "
                f"{target_page_count + 1} = append)"
            )
        )
        position_row.addStretch(1)

        # ---- Buttons --------------------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"Source: {source_path.name} ({source_page_count} page"
                f"{'s' if source_page_count != 1 else ''})"
            )
        )
        layout.addLayout(source_row)
        layout.addLayout(position_row)
        layout.addWidget(buttons)

    # ---- Spinbox sync -------------------------------------------------------

    def _sync_to_min(self, value: int) -> None:
        if self._to_spin.value() < value:
            self._to_spin.setValue(value)

    def _sync_from_max(self, value: int) -> None:
        if self._from_spin.value() > value:
            self._from_spin.setValue(value)

    # ---- Public properties --------------------------------------------------

    @property
    def source_range(self) -> tuple[int, int]:
        """Return 0-based inclusive ``(from_idx, to_idx)``."""
        return (self._from_spin.value() - 1, self._to_spin.value() - 1)

    @property
    def target_position(self) -> int:
        """Return 0-based insertion index for ``adapter.insert_pdf(at_index=...)``."""
        return self._position_spin.value() - 1

"""Crop-margins dialog for Edit -> Page -> Crop....

Collects four crop margins (top, right, bottom, left) in PDF points and
returns them as a tuple. Includes a Reset button that zeroes all four
fields, which the caller can use to clear an existing crop via
``crop_page(i, (0, 0, 0, 0))``.

The dialog shows the source page's dimensions for reference but does not
preview the resulting page; preview is deferred to PR 9 where the
Organize panel will provide a richer page-operations UI.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class CropDialog(QDialog):
    """Modal: four margin fields (top/right/bottom/left) in PDF points."""

    def __init__(
        self,
        page_index: int,
        page_width: float,
        page_height: float,
        initial_margins: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Crop Page {page_index + 1}")
        self.setModal(True)

        self._page_width = page_width
        self._page_height = page_height

        info_label = QLabel(
            f"Page {page_index + 1} dimensions: "
            f"{page_width:.1f} \u00d7 {page_height:.1f} points "
            f"({page_width / 72:.2f} \u00d7 {page_height / 72:.2f} inches)"
        )
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Spinboxes: range 0..(dim - 1) so the crop never collapses to zero.
        top, right, bottom, left = initial_margins
        self._top = self._make_spin(page_height - 1.0, top)
        self._right = self._make_spin(page_width - 1.0, right)
        self._bottom = self._make_spin(page_height - 1.0, bottom)
        self._left = self._make_spin(page_width - 1.0, left)

        form = QFormLayout()
        form.addRow("Top (points):", self._top)
        form.addRow("Right (points):", self._right)
        form.addRow("Bottom (points):", self._bottom)
        form.addRow("Left (points):", self._left)

        # Reset all to 0 to clear an existing crop.
        reset_btn = QPushButton("Reset (clear crop)")
        reset_btn.clicked.connect(self._reset)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.addWidget(reset_btn)
        button_row.addStretch(1)
        button_row.addWidget(button_box)

        layout = QVBoxLayout(self)
        layout.addWidget(info_label)
        layout.addSpacing(6)
        layout.addLayout(form)
        layout.addSpacing(6)
        layout.addLayout(button_row)

    @staticmethod
    def _make_spin(maximum: float, value: float) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(0.0, max(maximum, 0.0))
        sb.setDecimals(2)
        sb.setSingleStep(1.0)
        sb.setValue(value)
        return sb

    def _reset(self) -> None:
        for sb in (self._top, self._right, self._bottom, self._left):
            sb.setValue(0.0)

    @property
    def margins(self) -> tuple[float, float, float, float]:
        """``(top, right, bottom, left)`` in PDF points."""
        return (
            self._top.value(),
            self._right.value(),
            self._bottom.value(),
            self._left.value(),
        )

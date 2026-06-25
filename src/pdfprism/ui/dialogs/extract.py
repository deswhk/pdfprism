"""Extract dialog: page range picker for text / image extraction.

Used by both File -> Extract -> Text... and File -> Extract -> Images...,
parameterized by ``kind`` so the title and labels match the operation.
"""

from enum import StrEnum

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class ExtractKind(StrEnum):
    """What is being extracted, used to label the dialog."""

    TEXT = "text"
    IMAGES = "images"


class ExtractDialog(QDialog):
    """Modal dialog: pick all-pages vs page-range, return the chosen ``range``.

    Read ``page_range`` after ``exec()`` returns ``Accepted``. The returned
    range uses 0-based half-open semantics matching ``ExtractService``.
    """

    def __init__(
        self,
        page_count: int,
        kind: ExtractKind,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        noun = "text" if kind == ExtractKind.TEXT else "images"
        self.setWindowTitle(f"Extract {noun}")

        self._all_radio = QRadioButton(f"All pages (1 - {page_count})")
        self._all_radio.setChecked(True)
        self._range_radio = QRadioButton("Page range:")

        button_group = QButtonGroup(self)
        button_group.addButton(self._all_radio)
        button_group.addButton(self._range_radio)

        self._from_spin = QSpinBox()
        self._from_spin.setRange(1, page_count)
        self._from_spin.setValue(1)

        self._to_spin = QSpinBox()
        self._to_spin.setRange(1, page_count)
        self._to_spin.setValue(page_count)

        range_row = QHBoxLayout()
        range_row.addWidget(self._range_radio)
        range_row.addWidget(QLabel("from"))
        range_row.addWidget(self._from_spin)
        range_row.addWidget(QLabel("to"))
        range_row.addWidget(self._to_spin)
        range_row.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Extract {noun} from:"))
        layout.addWidget(self._all_radio)
        layout.addLayout(range_row)
        layout.addWidget(buttons)

        # Toggle spin enabled state with the radio.
        self._from_spin.setEnabled(False)
        self._to_spin.setEnabled(False)
        self._range_radio.toggled.connect(self._from_spin.setEnabled)
        self._range_radio.toggled.connect(self._to_spin.setEnabled)

        self._page_count = page_count

    @property
    def page_range(self) -> range:
        """0-based half-open range that matches ``ExtractService`` kwargs.

        All-pages selection returns ``range(0, page_count)``.
        Range selection returns ``range(from-1, to)`` (inclusive 1-based UI
        translated to 0-based half-open Python).
        """
        if self._all_radio.isChecked():
            return range(0, self._page_count)
        return range(self._from_spin.value() - 1, self._to_spin.value())

"""Redaction session options dialog (PR 12.3).

Session-level configuration for redaction defaults:

- **Fill color**: RGB color used for pending marks and after apply
  (unless overridden per-Redaction). Default black.
- **Replacement text**: optional overlay text drawn in the redacted
  area after apply (e.g. "[REDACTED]"). Default none.
- **Apply behavior**: exposes PyMuPDF's ``images``, ``graphics``,
  and ``text`` kwargs from ``apply_redactions()``. See PyMuPDF docs
  for the semantics; sensible defaults are pre-selected.

Values are persisted via ``QSettings`` from MainWindow, not this
dialog -- the dialog is dumb, just presents current values and
exposes accessors after Accepted.
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class RedactionOptionsDialog(QDialog):
    """Session-level redaction options."""

    # Combo box items: (label, value)
    _IMAGES_OPTIONS = (
        ("Remove entirely", 2),
        ("Blank fill", 1),
        ("Leave alone", 0),
    )
    _GRAPHICS_OPTIONS = (
        ("Remove", 1),
        ("Leave alone", 0),
    )
    _TEXT_OPTIONS = (
        ("Only inside rect", 0),
        ("Whole line", 1),
    )

    def __init__(
        self,
        *,
        fill_color: tuple[int, int, int] = (0, 0, 0),
        replacement_text: str | None = None,
        images: int = 2,
        graphics: int = 1,
        text: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Redaction Options")
        self.setModal(True)

        self._fill_color = fill_color
        self._build_ui(
            fill_color=fill_color,
            replacement_text=replacement_text,
            images=images,
            graphics=graphics,
            text=text,
        )

    def _build_ui(
        self,
        *,
        fill_color: tuple[int, int, int],
        replacement_text: str | None,
        images: int,
        graphics: int,
        text: int,
    ) -> None:
        root = QVBoxLayout(self)

        # ---- Marks section ----
        marks_label = QLabel("Mark appearance")
        marks_label.setStyleSheet("font-weight: bold;")
        root.addWidget(marks_label)

        marks_form = QFormLayout()

        # Fill color
        color_row = QHBoxLayout()
        self._color_swatch = QLabel()
        self._color_swatch.setFixedSize(40, 20)
        self._color_swatch.setAutoFillBackground(True)
        self._update_swatch()
        self._pick_color_button = QPushButton("Pick color...")
        self._pick_color_button.clicked.connect(self._on_pick_color)
        color_row.addWidget(self._color_swatch)
        color_row.addWidget(self._pick_color_button)
        color_row.addStretch()
        marks_form.addRow("Fill color:", color_row)

        # Replacement text
        self._replacement_input = QLineEdit()
        if replacement_text is not None:
            self._replacement_input.setText(replacement_text)
        self._replacement_input.setPlaceholderText("(none)")
        marks_form.addRow("Replacement text:", self._replacement_input)

        root.addLayout(marks_form)

        # ---- Apply behavior section ----
        apply_label = QLabel("Apply behavior")
        apply_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        root.addWidget(apply_label)

        apply_form = QFormLayout()

        self._images_combo = self._make_combo(self._IMAGES_OPTIONS, images)
        apply_form.addRow("Images:", self._images_combo)

        self._graphics_combo = self._make_combo(self._GRAPHICS_OPTIONS, graphics)
        apply_form.addRow("Graphics:", self._graphics_combo)

        self._text_combo = self._make_combo(self._TEXT_OPTIONS, text)
        apply_form.addRow("Surrounding text:", self._text_combo)

        root.addLayout(apply_form)

        # ---- OK / Cancel ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _make_combo(self, options: tuple[tuple[str, int], ...], current: int) -> QComboBox:
        combo = QComboBox()
        for label, value in options:
            combo.addItem(label, value)
        # Select the current value
        for i in range(combo.count()):
            if combo.itemData(i) == current:
                combo.setCurrentIndex(i)
                break
        return combo

    def _update_swatch(self) -> None:
        r, g, b = self._fill_color
        self._color_swatch.setStyleSheet(
            f"background-color: rgb({r}, {g}, {b}); border: 1px solid #999;"
        )

    def _on_pick_color(self) -> None:
        r, g, b = self._fill_color
        initial = QColor(r, g, b)
        chosen = QColorDialog.getColor(initial, self, "Pick Redaction Fill Color")
        if chosen.isValid():
            self._fill_color = (chosen.red(), chosen.green(), chosen.blue())
            self._update_swatch()

    # ---- Public accessors (call after exec() when Accepted) ----

    @property
    def fill_color(self) -> tuple[int, int, int]:
        return self._fill_color

    @property
    def replacement_text(self) -> str | None:
        text = self._replacement_input.text()
        return text if text else None

    @property
    def images(self) -> int:
        return self._images_combo.currentData()

    @property
    def graphics(self) -> int:
        return self._graphics_combo.currentData()

    @property
    def text_mode(self) -> int:
        return self._text_combo.currentData()

    def all_values(self) -> dict:
        return {
            "fill_color": self.fill_color,
            "replacement_text": self.replacement_text,
            "images": self.images,
            "graphics": self.graphics,
            "text": self.text_mode,
        }

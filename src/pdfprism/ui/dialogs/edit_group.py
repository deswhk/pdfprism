"""Edit Group dialog (PR 14b).

Compact per-group editor for pending redaction marks. Right-click on a
mark -> "Edit This Group..." (or "Edit This Mark..." for singletons)
opens this dialog scoped to the mark's group.

The dialog exposes two fields: fill color (picker) and replacement text
(line edit). When Accepted, the caller reads these via the properties
and applies them to every mark in the group via
``RedactionService.update_redaction_group``.

A "Reset to Global" button is enabled only when the group is currently
customized. Clicking it clears the override -- caller re-applies session
defaults (visible as ``was_reset`` returning True on the dialog).

The dialog is dumb: it does not touch the adapter or MainWindow state.
Caller is responsible for wiring the OK / Reset outcomes.
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
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


class EditGroupDialog(QDialog):
    """Editor for one redaction group's fill/text values."""

    def __init__(
        self,
        *,
        group_display_text: str,
        group_size: int,
        is_customized: bool,
        current_fill: tuple[int, int, int],
        current_text: str | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Redaction Group")
        self.setModal(True)

        self._fill_color = current_fill
        self._was_reset = False
        self._build_ui(
            group_display_text=group_display_text,
            group_size=group_size,
            is_customized=is_customized,
            current_text=current_text,
        )

    def _build_ui(
        self,
        *,
        group_display_text: str,
        group_size: int,
        is_customized: bool,
        current_text: str | None,
    ) -> None:
        root = QVBoxLayout(self)

        # Header
        if group_size == 1:
            header_text = "Editing 1 mark"
        else:
            header_text = f'Editing {group_size} marks matching "{group_display_text}"'
        header = QLabel(header_text)
        root.addWidget(header)

        marks_label = QLabel("Mark appearance")
        marks_label.setStyleSheet("font-weight: bold; margin-top: 4px;")
        root.addWidget(marks_label)

        form = QFormLayout()

        # Fill color row
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
        form.addRow("Fill color:", color_row)

        # Replacement text
        self._replacement_input = QLineEdit()
        if current_text is not None:
            self._replacement_input.setText(current_text)
        self._replacement_input.setPlaceholderText("(none)")
        form.addRow("Replacement text:", self._replacement_input)

        root.addLayout(form)

        # State indicator
        state_text = (
            "Currently using: Custom values"
            if is_customized
            else "Currently using: Global defaults"
        )
        state_label = QLabel(state_text)
        state_label.setStyleSheet("font-style: italic;")
        root.addWidget(state_label)

        # Buttons: Reset (if customized) | Cancel | OK
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._reset_button = QPushButton("Reset to Global")
        self._reset_button.setEnabled(is_customized)
        self._reset_button.clicked.connect(self._on_reset_to_global)
        buttons.addButton(self._reset_button, QDialogButtonBox.ButtonRole.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

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

    def _on_reset_to_global(self) -> None:
        """User clicked Reset to Global -- flag and accept immediately.

        Caller reads ``was_reset`` to know the group should adopt current
        session defaults instead of the dialog's fill/text values.
        """
        self._was_reset = True
        self.accept()

    # ---- Public accessors ----

    @property
    def fill_color(self) -> tuple[int, int, int]:
        return self._fill_color

    @property
    def replacement_text(self) -> str | None:
        text = self._replacement_input.text()
        return text if text else None

    @property
    def was_reset(self) -> bool:
        """True if user clicked Reset to Global instead of OK."""
        return self._was_reset

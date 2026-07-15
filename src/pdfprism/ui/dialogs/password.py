"""Password prompt for opening encrypted PDFs.

Modal dialog shown by MainWindow when opening a PDF raises
``PasswordRequiredError``. The dialog is designed to be reusable across
retry attempts: the caller keeps the instance, calls ``set_error_message``
after a failed attempt, and re-invokes ``exec()``. No per-attempt
construction cost, and the dialog stays in the same screen position.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


class PasswordDialog(QDialog):
    """Modal: masked password input for opening an encrypted PDF.

    The dialog is intentionally simple. Password max length is not
    enforced -- PyMuPDF's ``authenticate()`` is the authority on
    whether a given string is a valid password.
    """

    def __init__(
        self,
        filename: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Password Required")
        self.setModal(True)

        self._info_label = QLabel(f"Enter password for '{filename}':")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        # Masked input by default. Enter key submits OK because the button
        # box's OK button is default (see button_box below).
        self._input = QLineEdit()
        self._input.setEchoMode(QLineEdit.EchoMode.Password)
        self._input.setPlaceholderText("Password")

        # Show-password toggle: small polish that helps users spot typos.
        self._show_checkbox = QCheckBox("Show password")
        self._show_checkbox.toggled.connect(self._on_show_toggled)

        # Error label: hidden until set_error_message is called with a
        # non-empty message. Uses a warning colour distinguishable in
        # both light and dark modes.
        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #c62828;")  # material red 800
        self._error_label.setVisible(False)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        # Layout: label -> input -> show-checkbox -> error (hidden) -> buttons.
        # Input+checkbox share a row for compactness.
        input_row = QHBoxLayout()
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._show_checkbox)

        layout = QVBoxLayout(self)
        layout.addWidget(self._info_label)
        layout.addLayout(input_row)
        layout.addWidget(self._error_label)
        layout.addWidget(button_box)

        # Focus the input so users can just type and press Enter.
        self._input.setFocus()

    # ---- Public API ---------------------------------------------------------

    @property
    def password(self) -> str:
        """The password the user entered. Empty string if never typed."""
        return self._input.text()

    def set_error_message(self, message: str | None) -> None:
        """Show or hide the retry error message.

        ``None`` or empty string hides the label; any other value shows
        it. Also clears the input field on a retry so the user starts
        fresh (typing over a wrong password is confusing).
        """
        if not message:
            self._error_label.setVisible(False)
            self._error_label.setText("")
            return
        self._error_label.setText(message)
        self._error_label.setVisible(True)
        # Clear the field on retry, keep focus in it.
        self._input.clear()
        self._input.setFocus()

    # ---- Internals ---------------------------------------------------------

    def _on_show_toggled(self, checked: bool) -> None:
        """Toggle the input's echo mode between Password and Normal."""
        self._input.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

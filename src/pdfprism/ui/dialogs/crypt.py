"""Encryption dialog for set / change / remove password (PR 10.5).

The dialog is a *reactive* form: mode is fixed at construction time
based on the document's current encryption state. On unencrypted docs
it collects a new password (with confirmation) for a "set password"
operation. On encrypted docs it collects a new password for "change
password" and offers a "Remove password instead" checkbox that
toggles into the "remove password" branch.

The dialog does not collect the *current* password because the caller
opens the dialog only after a successful authenticated open -- the
adapter already knows the current password.

The dialog performs *client-side* validation only (fields match,
non-empty). Server-side rules (whitespace-only passwords, state /
intent mismatch) are enforced by ``SecurityService`` and surface as
``EncryptionOperationError`` if they slip through.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


class CryptDialog(QDialog):
    """Modal: set / change / remove password.

    Mode selection is by ``is_encrypted`` at construction time:

    - ``is_encrypted=False``: "Set password" mode. New + Confirm fields.
      OK enabled when both match and are non-empty.
    - ``is_encrypted=True``: "Change password" mode by default. Same
      fields. A "Remove password instead" checkbox flips into "Remove"
      mode -- fields are disabled and OK is always enabled.
    """

    def __init__(
        self,
        is_encrypted: bool,
        filename: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_encrypted = is_encrypted
        title = "Change Password" if is_encrypted else "Set Password"
        self.setWindowTitle(title)
        self.setModal(True)

        # Contextual info label
        if is_encrypted:
            info_text = f"Change the password for '{filename}', or remove it entirely."
        else:
            info_text = f"Set a password to encrypt '{filename}'."
        self._info_label = QLabel(info_text)
        self._info_label.setWordWrap(True)

        # ---- Password inputs ---------------------------------------------
        self._new_input = QLineEdit()
        self._new_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._new_input.setPlaceholderText("New password")
        self._new_input.textChanged.connect(self._refresh_ok_state)

        self._confirm_input = QLineEdit()
        self._confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._confirm_input.setPlaceholderText("Confirm password")
        self._confirm_input.textChanged.connect(self._refresh_ok_state)

        self._show_checkbox = QCheckBox("Show password")
        self._show_checkbox.toggled.connect(self._on_show_toggled)

        # ---- Optional Remove branch (only in encrypted mode) --------------
        self._remove_checkbox: QCheckBox | None = None
        if is_encrypted:
            self._remove_checkbox = QCheckBox("Remove password instead (make document unencrypted)")
            self._remove_checkbox.toggled.connect(self._on_remove_toggled)

        # ---- Mismatch feedback -------------------------------------------
        self._mismatch_label = QLabel("Passwords do not match.")
        self._mismatch_label.setStyleSheet("color: #c62828;")
        self._mismatch_label.setVisible(False)

        # ---- Buttons -----------------------------------------------------
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)

        # ---- Layout ------------------------------------------------------
        form = QFormLayout()
        form.addRow("New password:", self._new_input)
        form.addRow("Confirm:", self._confirm_input)

        layout = QVBoxLayout(self)
        layout.addWidget(self._info_label)
        layout.addLayout(form)
        layout.addWidget(self._show_checkbox)
        if self._remove_checkbox is not None:
            layout.addWidget(self._remove_checkbox)
        layout.addWidget(self._mismatch_label)
        layout.addWidget(self._button_box)

        # Initial state: OK disabled until fields match.
        self._refresh_ok_state()
        self._new_input.setFocus()

    # ---- Public API ---------------------------------------------------------

    @property
    def new_password(self) -> str:
        """The new password. Empty string when remove_requested is True."""
        if self.remove_requested:
            return ""
        return self._new_input.text()

    @property
    def remove_requested(self) -> bool:
        """True when the user checked the Remove branch (encrypted mode only)."""
        return self._remove_checkbox is not None and self._remove_checkbox.isChecked()

    # ---- Internals ---------------------------------------------------------

    def _refresh_ok_state(self) -> None:
        """Enable OK based on the current fields + remove-state."""
        ok_btn = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is None:
            return

        if self.remove_requested:
            # Remove mode: OK is always enabled, mismatch label hidden.
            ok_btn.setEnabled(True)
            self._mismatch_label.setVisible(False)
            return

        new = self._new_input.text()
        confirm = self._confirm_input.text()

        # Show mismatch label only when confirm has been typed and
        # differs from new (avoids flashing the warning on every
        # keystroke into new_input).
        show_mismatch = bool(confirm) and (new != confirm)
        self._mismatch_label.setVisible(show_mismatch)

        # OK enabled iff both fields are non-empty AND match.
        ok_btn.setEnabled(bool(new) and new == confirm)

    def _on_show_toggled(self, checked: bool) -> None:
        """Show/hide password toggle covers both fields uniformly."""
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self._new_input.setEchoMode(mode)
        self._confirm_input.setEchoMode(mode)

    def _on_remove_toggled(self, checked: bool) -> None:
        """Toggling Remove disables/enables the password fields."""
        self._new_input.setEnabled(not checked)
        self._confirm_input.setEnabled(not checked)
        self._show_checkbox.setEnabled(not checked)
        self._refresh_ok_state()

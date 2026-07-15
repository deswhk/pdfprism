"""Tests for CryptDialog."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialogButtonBox, QLineEdit

from pdfprism.ui.dialogs.crypt import CryptDialog


@pytest.fixture
def set_dialog(qtbot) -> CryptDialog:
    dlg = CryptDialog(is_encrypted=False, filename="report.pdf")
    qtbot.addWidget(dlg)
    return dlg


@pytest.fixture
def change_dialog(qtbot) -> CryptDialog:
    dlg = CryptDialog(is_encrypted=True, filename="secret.pdf")
    qtbot.addWidget(dlg)
    return dlg


def _ok_button(dlg: CryptDialog):
    return dlg._button_box.button(QDialogButtonBox.StandardButton.Ok)


# =========================================================================
# Unencrypted mode ("Set password")
# =========================================================================


class TestUnencryptedMode:
    """is_encrypted=False -> Set Password mode; no Remove checkbox."""

    def test_title_is_set_password(self, set_dialog: CryptDialog) -> None:
        assert set_dialog.windowTitle() == "Set Password"

    def test_info_label_mentions_filename(self, set_dialog: CryptDialog) -> None:
        assert "report.pdf" in set_dialog._info_label.text()

    def test_no_remove_checkbox(self, set_dialog: CryptDialog) -> None:
        """Negative check: Remove branch is only for encrypted docs."""
        assert set_dialog._remove_checkbox is None

    def test_ok_disabled_initially(self, set_dialog: CryptDialog) -> None:
        """Negative: empty fields -> OK disabled."""
        assert _ok_button(set_dialog).isEnabled() is False

    def test_ok_disabled_with_only_new_field_filled(self, set_dialog: CryptDialog) -> None:
        """Negative: new filled, confirm empty -> OK still disabled."""
        set_dialog._new_input.setText("hunter2")
        assert _ok_button(set_dialog).isEnabled() is False

    def test_mismatch_shown_when_fields_diverge(self, set_dialog: CryptDialog) -> None:
        """Positive: typing different values in the two fields shows warning."""
        set_dialog._new_input.setText("hunter2")
        set_dialog._confirm_input.setText("wrong")
        # isVisibleTo(parent) checks the widget's own visibility flag
        # without requiring the parent dialog to actually be shown.
        assert set_dialog._mismatch_label.isVisibleTo(set_dialog) is True

    def test_mismatch_hidden_when_fields_match(self, set_dialog: CryptDialog) -> None:
        """Positive: matching -> mismatch label hidden."""
        set_dialog._new_input.setText("hunter2")
        set_dialog._confirm_input.setText("hunter2")
        assert set_dialog._mismatch_label.isVisibleTo(set_dialog) is False

    def test_ok_enabled_when_fields_match_and_non_empty(self, set_dialog: CryptDialog) -> None:
        """Positive: matching non-empty passwords -> OK enabled."""
        set_dialog._new_input.setText("hunter2")
        set_dialog._confirm_input.setText("hunter2")
        assert _ok_button(set_dialog).isEnabled() is True

    def test_new_password_property_returns_typed(self, set_dialog: CryptDialog) -> None:
        """Positive: property returns whatever's in the new field."""
        set_dialog._new_input.setText("hunter2")
        set_dialog._confirm_input.setText("hunter2")
        assert set_dialog.new_password == "hunter2"

    def test_remove_requested_always_false_in_set_mode(self, set_dialog: CryptDialog) -> None:
        """Negative regression: unencrypted mode has no Remove branch."""
        assert set_dialog.remove_requested is False


# =========================================================================
# Encrypted mode ("Change / Remove password")
# =========================================================================


class TestEncryptedMode:
    """is_encrypted=True -> Change Password mode with Remove option."""

    def test_title_is_change_password(self, change_dialog: CryptDialog) -> None:
        assert change_dialog.windowTitle() == "Change Password"

    def test_remove_checkbox_present(self, change_dialog: CryptDialog) -> None:
        """Positive: Remove checkbox exists in encrypted mode."""
        assert change_dialog._remove_checkbox is not None
        assert change_dialog._remove_checkbox.isChecked() is False

    def test_remove_toggle_disables_password_fields(self, change_dialog: CryptDialog) -> None:
        """Positive: checking Remove disables the New / Confirm fields."""
        change_dialog._remove_checkbox.setChecked(True)
        assert change_dialog._new_input.isEnabled() is False
        assert change_dialog._confirm_input.isEnabled() is False
        assert change_dialog._show_checkbox.isEnabled() is False

    def test_remove_toggle_enables_ok_immediately(self, change_dialog: CryptDialog) -> None:
        """Positive: OK enabled in Remove mode regardless of fields."""
        assert _ok_button(change_dialog).isEnabled() is False  # empty
        change_dialog._remove_checkbox.setChecked(True)
        assert _ok_button(change_dialog).isEnabled() is True

    def test_remove_untoggle_re_enables_fields(self, change_dialog: CryptDialog) -> None:
        """Positive: unchecking Remove restores password-field mode."""
        change_dialog._remove_checkbox.setChecked(True)
        change_dialog._remove_checkbox.setChecked(False)
        assert change_dialog._new_input.isEnabled() is True
        assert change_dialog._confirm_input.isEnabled() is True
        # OK back to disabled because fields are empty
        assert _ok_button(change_dialog).isEnabled() is False

    def test_remove_requested_true_when_checked(self, change_dialog: CryptDialog) -> None:
        """Positive: remove_requested tracks the checkbox."""
        assert change_dialog.remove_requested is False
        change_dialog._remove_checkbox.setChecked(True)
        assert change_dialog.remove_requested is True

    def test_new_password_returns_empty_when_remove_checked(
        self, change_dialog: CryptDialog
    ) -> None:
        """Positive: even with fields filled, remove-mode ignores them."""
        change_dialog._new_input.setText("this should be ignored")
        change_dialog._confirm_input.setText("this should be ignored")
        change_dialog._remove_checkbox.setChecked(True)
        assert change_dialog.new_password == ""


# =========================================================================
# Cross-mode: show-password toggle
# =========================================================================


class TestShowPasswordToggle:
    """The show-password checkbox toggles both fields uniformly."""

    def test_toggle_on_shows_both_fields(self, set_dialog: CryptDialog) -> None:
        """Positive: toggle affects new + confirm together."""
        set_dialog._show_checkbox.setChecked(True)
        assert set_dialog._new_input.echoMode() == QLineEdit.EchoMode.Normal
        assert set_dialog._confirm_input.echoMode() == QLineEdit.EchoMode.Normal

    def test_toggle_off_masks_both_fields(self, set_dialog: CryptDialog) -> None:
        """Positive: toggle off returns to masked mode."""
        set_dialog._show_checkbox.setChecked(True)
        set_dialog._show_checkbox.setChecked(False)
        assert set_dialog._new_input.echoMode() == QLineEdit.EchoMode.Password
        assert set_dialog._confirm_input.echoMode() == QLineEdit.EchoMode.Password

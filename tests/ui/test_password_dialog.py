"""Tests for PasswordDialog."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLineEdit

from pdfprism.ui.dialogs.password import PasswordDialog


@pytest.fixture
def dialog(qtbot) -> PasswordDialog:
    dlg = PasswordDialog("secret.pdf")
    qtbot.addWidget(dlg)
    return dlg


class TestConstruction:
    """The dialog constructs correctly and shows the file context."""

    def test_title(self, dialog: PasswordDialog) -> None:
        assert dialog.windowTitle() == "Password Required"

    def test_info_label_shows_filename(self, dialog: PasswordDialog) -> None:
        assert "secret.pdf" in dialog._info_label.text()

    def test_input_starts_masked(self, dialog: PasswordDialog) -> None:
        """Positive: echo mode defaults to Password (masked)."""
        assert dialog._input.echoMode() == QLineEdit.EchoMode.Password

    def test_input_is_initial_focus_widget(self, dialog: PasswordDialog, qtbot) -> None:
        """Positive: the input is the designated initial-focus widget.

        Testing ``hasFocus()`` after ``show()`` alone is fragile because
        the test environment may not grant an active window; a
        show->activateWindow->waitUntil dance works interactively but
        can still flake offscreen. Instead we check ``focusWidget()``
        after activating the window -- that is the design guarantee we
        actually care about (the layout designates the input as first
        in the focus chain), regardless of whether the OS granted
        window-level focus.
        """
        dialog.show()
        qtbot.waitExposed(dialog)
        dialog.activateWindow()
        # Poll until Qt has processed the activation. Falls back to a
        # focusWidget() check because hasFocus() depends on window
        # activation which is flaky offscreen.
        qtbot.waitUntil(lambda: dialog.focusWidget() is dialog._input, timeout=1000)
        assert dialog.focusWidget() is dialog._input

    def test_error_label_initially_hidden(self, dialog: PasswordDialog) -> None:
        """Negative: no error state at construction time."""
        assert dialog._error_label.isVisible() is False


class TestPasswordProperty:
    """password property returns the typed text."""

    def test_typed_text_returned(self, dialog: PasswordDialog) -> None:
        """Positive: text set programmatically is returned."""
        dialog._input.setText("hunter2")
        assert dialog.password == "hunter2"

    def test_empty_input_returns_empty_string(self, dialog: PasswordDialog) -> None:
        """Negative: nothing typed -> empty string, not None."""
        assert dialog.password == ""


class TestShowPasswordToggle:
    """Show-password checkbox flips echo mode."""

    def test_toggle_on_shows_password(self, dialog: PasswordDialog) -> None:
        """Positive: checking the box switches echo mode to Normal."""
        dialog._show_checkbox.setChecked(True)
        assert dialog._input.echoMode() == QLineEdit.EchoMode.Normal

    def test_toggle_off_masks_password(self, dialog: PasswordDialog) -> None:
        """Positive: un-checking returns to Password echo mode."""
        dialog._show_checkbox.setChecked(True)
        dialog._show_checkbox.setChecked(False)
        assert dialog._input.echoMode() == QLineEdit.EchoMode.Password


class TestSetErrorMessage:
    """Error label visibility + retry-loop input clearing."""

    def test_set_message_shows_label(self, dialog: PasswordDialog) -> None:
        """Positive: non-empty message -> label visible with that text."""
        # Need to show the dialog for visibility semantics to be correct.
        dialog.show()
        dialog.set_error_message("Incorrect password. Try again.")
        assert dialog._error_label.isVisible() is True
        assert dialog._error_label.text() == "Incorrect password. Try again."

    def test_set_none_hides_label(self, dialog: PasswordDialog) -> None:
        """Positive: None argument hides the label."""
        dialog.show()
        dialog.set_error_message("Something went wrong")
        assert dialog._error_label.isVisible() is True
        dialog.set_error_message(None)
        assert dialog._error_label.isVisible() is False

    def test_set_empty_string_hides_label(self, dialog: PasswordDialog) -> None:
        """Negative: empty string treated like None."""
        dialog.show()
        dialog.set_error_message("Try again")
        dialog.set_error_message("")
        assert dialog._error_label.isVisible() is False

    def test_error_clears_input(self, dialog: PasswordDialog) -> None:
        """Positive (design invariant): retry starts with a fresh field.

        Typing over a wrong password is confusing; we clear so the user
        starts from an empty state.
        """
        dialog._input.setText("wrongpassword")
        dialog.set_error_message("Incorrect password. Try again.")
        assert dialog.password == ""

    def test_error_returns_focus_to_input(self, dialog: PasswordDialog, qtbot) -> None:
        """Positive: focus returns to the input after the retry banner appears.

        User pressed Enter with a wrong password -- they want to keep
        typing right away, not have to click back into the field.

        Tests ``focusWidget()`` (the widget the layout designates as
        holding focus) rather than ``hasFocus()`` (which additionally
        requires the OS to have activated the window -- fragile under
        the offscreen Qt platform used in headless CI).
        """
        dialog.show()
        qtbot.waitExposed(dialog)
        dialog.activateWindow()
        # Move focus elsewhere first to prove set_error_message returns it.
        dialog._show_checkbox.setFocus()
        qtbot.waitUntil(
            lambda: dialog.focusWidget() is dialog._show_checkbox,
            timeout=1000,
        )
        dialog.set_error_message("Wrong")
        qtbot.waitUntil(lambda: dialog.focusWidget() is dialog._input, timeout=1000)
        assert dialog.focusWidget() is dialog._input

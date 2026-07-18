"""Widget tests for EditGroupDialog (PR 14b)."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog

from pdfprism.ui.dialogs.edit_group import EditGroupDialog


class TestConstruction:
    def test_builds_with_multi_mark_group(self, qtbot) -> None:
        """Positive: dialog constructs for group of many marks."""
        dlg = EditGroupDialog(
            group_display_text="John Smith",
            group_size=3,
            is_customized=False,
            current_fill=(0, 0, 0),
            current_text=None,
        )
        qtbot.addWidget(dlg)
        assert dlg.windowTitle() == "Edit Redaction Group"

    def test_builds_with_singleton(self, qtbot) -> None:
        """Positive: dialog constructs for group of 1."""
        dlg = EditGroupDialog(
            group_display_text="unique",
            group_size=1,
            is_customized=True,
            current_fill=(255, 0, 0),
            current_text="[X]",
        )
        qtbot.addWidget(dlg)
        assert dlg is not None


class TestResetButton:
    def test_disabled_when_not_customized(self, qtbot) -> None:
        """Positive: Reset button disabled for Global groups."""
        dlg = EditGroupDialog(
            group_display_text="X",
            group_size=2,
            is_customized=False,
            current_fill=(0, 0, 0),
            current_text=None,
        )
        qtbot.addWidget(dlg)
        assert dlg._reset_button.isEnabled() is False

    def test_enabled_when_customized(self, qtbot) -> None:
        """Positive: Reset button enabled for Custom groups."""
        dlg = EditGroupDialog(
            group_display_text="X",
            group_size=2,
            is_customized=True,
            current_fill=(255, 0, 0),
            current_text="[X]",
        )
        qtbot.addWidget(dlg)
        assert dlg._reset_button.isEnabled() is True

    def test_reset_click_sets_flag_and_accepts(self, qtbot) -> None:
        """Positive: clicking Reset -> was_reset=True + dialog accepts."""
        dlg = EditGroupDialog(
            group_display_text="X",
            group_size=2,
            is_customized=True,
            current_fill=(255, 0, 0),
            current_text="[X]",
        )
        qtbot.addWidget(dlg)
        # Directly invoke the slot (avoids modal exec)
        dlg._on_reset_to_global()
        assert dlg.was_reset is True
        assert dlg.result() == QDialog.DialogCode.Accepted


class TestAccessors:
    def test_fill_color_returns_provided(self, qtbot) -> None:
        """Positive: fill_color property returns constructor value."""
        dlg = EditGroupDialog(
            group_display_text="X",
            group_size=1,
            is_customized=True,
            current_fill=(200, 100, 50),
            current_text="[X]",
        )
        qtbot.addWidget(dlg)
        assert dlg.fill_color == (200, 100, 50)

    def test_replacement_text_returns_current(self, qtbot) -> None:
        """Positive: replacement_text returns current input value."""
        dlg = EditGroupDialog(
            group_display_text="X",
            group_size=1,
            is_customized=True,
            current_fill=(0, 0, 0),
            current_text="[REDACTED]",
        )
        qtbot.addWidget(dlg)
        assert dlg.replacement_text == "[REDACTED]"

    def test_empty_replacement_text_returns_none(self, qtbot) -> None:
        """Positive: empty text field -> None."""
        dlg = EditGroupDialog(
            group_display_text="X",
            group_size=1,
            is_customized=False,
            current_fill=(0, 0, 0),
            current_text=None,
        )
        qtbot.addWidget(dlg)
        assert dlg.replacement_text is None

"""Widget tests for RedactionOptionsDialog (PR 12.3)."""

from __future__ import annotations

from pdfprism.ui.dialogs.redaction_options import RedactionOptionsDialog


class TestConstruction:
    def test_builds_with_defaults(self, qtbot) -> None:
        """Positive: dialog constructs with default values."""
        dlg = RedactionOptionsDialog()
        qtbot.addWidget(dlg)
        assert dlg.windowTitle() == "Redaction Options"

    def test_builds_with_custom_values(self, qtbot) -> None:
        """Positive: dialog constructs with all custom params."""
        dlg = RedactionOptionsDialog(
            fill_color=(255, 128, 64),
            replacement_text="[GONE]",
            images=1,
            graphics=0,
            text=1,
        )
        qtbot.addWidget(dlg)
        assert dlg is not None


class TestAccessors:
    def test_fill_color_returns_provided(self, qtbot) -> None:
        """Positive: fill_color property returns the value passed in."""
        dlg = RedactionOptionsDialog(fill_color=(200, 100, 50))
        qtbot.addWidget(dlg)
        assert dlg.fill_color == (200, 100, 50)

    def test_all_values_returns_full_dict(self, qtbot) -> None:
        """Positive: all_values returns a dict of every setting."""
        dlg = RedactionOptionsDialog(
            fill_color=(200, 100, 50),
            replacement_text="[X]",
            images=1,
            graphics=0,
            text=1,
        )
        qtbot.addWidget(dlg)
        values = dlg.all_values()
        assert values["fill_color"] == (200, 100, 50)
        assert values["replacement_text"] == "[X]"
        assert values["images"] == 1
        assert values["graphics"] == 0
        assert values["text"] == 1

    def test_empty_replacement_text_returns_none(self, qtbot) -> None:
        """Positive: empty text field -> None (clear-field convention)."""
        dlg = RedactionOptionsDialog(replacement_text=None)
        qtbot.addWidget(dlg)
        assert dlg.replacement_text is None

    def test_combo_selections_readable(self, qtbot) -> None:
        """Positive: combo box selections match constructor kwargs."""
        dlg = RedactionOptionsDialog(images=0, graphics=1, text=0)
        qtbot.addWidget(dlg)
        assert dlg.images == 0
        assert dlg.graphics == 1
        assert dlg.text_mode == 0

"""Widget tests for CombineDialog (PR 16)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from pdfprism.ui.dialogs.combine import CombineDialog


def _add_source(dlg: CombineDialog, name: str) -> None:
    """Helper: add a fake source path to the dialog's list."""
    p = Path(f"/fake/{name}")
    item = QListWidgetItem(p.name)
    item.setData(Qt.ItemDataRole.UserRole, str(p))
    dlg._list.addItem(item)
    dlg._refresh_buttons()


class TestConstruction:
    def test_builds_with_empty_list(self, qtbot) -> None:
        """Positive: dialog constructs with empty list."""
        dlg = CombineDialog()
        qtbot.addWidget(dlg)
        assert dlg.windowTitle() == "Combine PDFs"
        assert dlg._list.count() == 0


class TestCombineButtonEnableState:
    def test_disabled_with_no_sources(self, qtbot) -> None:
        """Positive: Combine disabled when list is empty."""
        dlg = CombineDialog()
        qtbot.addWidget(dlg)
        assert dlg._combine_button.isEnabled() is False

    def test_disabled_with_one_source(self, qtbot) -> None:
        """Positive: Combine disabled with only one source (need 2 min)."""
        dlg = CombineDialog()
        qtbot.addWidget(dlg)
        _add_source(dlg, "only.pdf")
        assert dlg._combine_button.isEnabled() is False

    def test_enabled_with_two_sources(self, qtbot) -> None:
        """Positive: Combine enabled with 2+ sources."""
        dlg = CombineDialog()
        qtbot.addWidget(dlg)
        _add_source(dlg, "a.pdf")
        _add_source(dlg, "b.pdf")
        assert dlg._combine_button.isEnabled() is True


class TestReordering:
    def test_move_up(self, qtbot) -> None:
        """Positive: Move Up swaps selected row with the one above."""
        dlg = CombineDialog()
        qtbot.addWidget(dlg)
        for name in ("first.pdf", "second.pdf", "third.pdf"):
            _add_source(dlg, name)
        # Move third up -> becomes second
        dlg._list.setCurrentRow(2)
        dlg._on_move_up()
        assert [p.name for p in dlg.sources] == [
            "first.pdf",
            "third.pdf",
            "second.pdf",
        ]

    def test_move_down(self, qtbot) -> None:
        """Positive: Move Down swaps selected with the one below."""
        dlg = CombineDialog()
        qtbot.addWidget(dlg)
        for name in ("a.pdf", "b.pdf", "c.pdf"):
            _add_source(dlg, name)
        dlg._list.setCurrentRow(0)
        dlg._on_move_down()
        assert [p.name for p in dlg.sources] == ["b.pdf", "a.pdf", "c.pdf"]

    def test_remove(self, qtbot) -> None:
        """Positive: Remove drops the selected row."""
        dlg = CombineDialog()
        qtbot.addWidget(dlg)
        for name in ("a.pdf", "b.pdf", "c.pdf"):
            _add_source(dlg, name)
        dlg._list.setCurrentRow(1)
        dlg._on_remove()
        assert [p.name for p in dlg.sources] == ["a.pdf", "c.pdf"]


class TestSourcesAccessor:
    def test_returns_paths_in_order(self, qtbot) -> None:
        """Positive: sources accessor returns Path list in visible order."""
        dlg = CombineDialog()
        qtbot.addWidget(dlg)
        _add_source(dlg, "one.pdf")
        _add_source(dlg, "two.pdf")
        result = dlg.sources
        assert all(isinstance(p, Path) for p in result)
        assert [p.name for p in result] == ["one.pdf", "two.pdf"]

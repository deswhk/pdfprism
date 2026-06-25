"""Tests for MergeDialog."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox

from pdfprism.ui.dialogs.merge import MergeDialog


@pytest.fixture
def dialog(tmp_path: Path, qtbot) -> MergeDialog:
    titles = ["A.pdf", "B.pdf", "C.pdf"]
    dlg = MergeDialog(
        tab_titles=titles,
        default_output_path=tmp_path / "merged.pdf",
    )
    qtbot.addWidget(dlg)
    return dlg


class TestDefaults:
    def test_title(self, dialog: MergeDialog) -> None:
        assert dialog.windowTitle() == "Merge Documents"

    def test_all_tabs_listed(self, dialog: MergeDialog) -> None:
        assert dialog._list.count() == 3

    def test_all_checked_by_default(self, dialog: MergeDialog) -> None:
        assert dialog.selected_tab_indices == [0, 1, 2]

    def test_default_output_path(self, dialog: MergeDialog, tmp_path: Path) -> None:
        assert dialog.output_path == tmp_path / "merged.pdf"


class TestSelection:
    def test_unchecking_excludes(self, dialog: MergeDialog) -> None:
        dialog._list.item(1).setCheckState(Qt.CheckState.Unchecked)
        assert dialog.selected_tab_indices == [0, 2]


class TestReorder:
    def test_move_down_swaps_with_next(self, dialog: MergeDialog) -> None:
        dialog._list.setCurrentRow(0)
        dialog._move_down()
        # Now order is B, A, C
        assert dialog.selected_tab_indices == [1, 0, 2]

    def test_move_up_swaps_with_prev(self, dialog: MergeDialog) -> None:
        dialog._list.setCurrentRow(2)
        dialog._move_up()
        # Now order is A, C, B
        assert dialog.selected_tab_indices == [0, 2, 1]

    def test_move_up_at_top_is_noop(self, dialog: MergeDialog) -> None:
        dialog._list.setCurrentRow(0)
        dialog._move_up()
        assert dialog.selected_tab_indices == [0, 1, 2]

    def test_move_down_at_bottom_is_noop(self, dialog: MergeDialog) -> None:
        dialog._list.setCurrentRow(2)
        dialog._move_down()
        assert dialog.selected_tab_indices == [0, 1, 2]

    def test_unchecked_item_kept_in_order_after_move(self, dialog: MergeDialog) -> None:
        # Uncheck B, then move A down past it; check stays consistent.
        dialog._list.item(1).setCheckState(Qt.CheckState.Unchecked)
        dialog._list.setCurrentRow(0)
        dialog._move_down()
        # Visual order: B, A, C; checked: A, C (B unchecked)
        assert dialog.selected_tab_indices == [0, 2]


class TestOkButton:
    def test_enabled_with_all_checked_and_path(self, dialog: MergeDialog) -> None:
        ok = dialog._button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok is not None
        assert ok.isEnabled() is True

    def test_disabled_with_one_checked(self, dialog: MergeDialog) -> None:
        dialog._list.item(1).setCheckState(Qt.CheckState.Unchecked)
        dialog._list.item(2).setCheckState(Qt.CheckState.Unchecked)
        ok = dialog._button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok is not None
        assert ok.isEnabled() is False

    def test_disabled_with_zero_checked(self, dialog: MergeDialog) -> None:
        for i in range(dialog._list.count()):
            dialog._list.item(i).setCheckState(Qt.CheckState.Unchecked)
        ok = dialog._button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok is not None
        assert ok.isEnabled() is False

    def test_disabled_without_output_path(self, dialog: MergeDialog) -> None:
        dialog._output_edit.setText("")
        ok = dialog._button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok is not None
        assert ok.isEnabled() is False

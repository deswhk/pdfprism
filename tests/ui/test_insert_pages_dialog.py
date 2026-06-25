"""Tests for InsertPagesDialog."""

from pathlib import Path

import pytest

from pdfprism.ui.dialogs.insert_pages import InsertPagesDialog


@pytest.fixture
def dialog(tmp_path: Path, qtbot) -> InsertPagesDialog:
    src = tmp_path / "source.pdf"
    src.touch()
    dlg = InsertPagesDialog(
        source_path=src,
        source_page_count=5,
        target_name="target.pdf",
        target_page_count=10,
        default_target_position=4,
    )
    qtbot.addWidget(dlg)
    return dlg


class TestDefaults:
    def test_source_range_defaults_to_full(self, dialog: InsertPagesDialog) -> None:
        assert dialog.source_range == (0, 4)  # 0-based inclusive of all 5

    def test_target_position_defaults_to_param(self, dialog: InsertPagesDialog) -> None:
        # default_target_position=4 (1-based) -> 0-based 3
        assert dialog.target_position == 3


class TestTargetPositionRange:
    def test_position_can_go_to_append(self, dialog: InsertPagesDialog) -> None:
        # target_page_count = 10, so position max is 11 (1-based);
        # that translates to 0-based 10 = append
        dialog._position_spin.setValue(11)
        assert dialog.target_position == 10

    def test_position_minimum_is_one(self, dialog: InsertPagesDialog) -> None:
        dialog._position_spin.setValue(1)
        assert dialog.target_position == 0  # prepend

    def test_default_position_clamped_when_out_of_range(self, tmp_path: Path, qtbot) -> None:
        # default 99 > target_page_count + 1 = 11, should clamp to 11
        src = tmp_path / "src.pdf"
        src.touch()
        dlg = InsertPagesDialog(
            source_path=src,
            source_page_count=3,
            target_name="t.pdf",
            target_page_count=10,
            default_target_position=99,
        )
        qtbot.addWidget(dlg)
        assert dlg.target_position == 10  # max position


class TestSourceRangeAdjustment:
    def test_from_above_to_drags_to(self, dialog: InsertPagesDialog) -> None:
        dialog._from_spin.setValue(4)
        dialog._to_spin.setValue(2)
        assert dialog._from_spin.value() == 2


class TestTitle:
    def test_title(self, dialog: InsertPagesDialog) -> None:
        assert dialog.windowTitle() == "Insert Pages from File"

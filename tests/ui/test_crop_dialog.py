"""Tests for CropDialog."""

import pytest

from pdfprism.ui.dialogs.crop import CropDialog


@pytest.fixture
def dialog(qtbot) -> CropDialog:
    dlg = CropDialog(page_index=0, page_width=612, page_height=792)
    qtbot.addWidget(dlg)
    return dlg


class TestDefaults:
    def test_default_margins_are_zero(self, dialog: CropDialog) -> None:
        assert dialog.margins == (0.0, 0.0, 0.0, 0.0)

    def test_initial_margins_respected(self, qtbot) -> None:
        dlg = CropDialog(
            page_index=0,
            page_width=612,
            page_height=792,
            initial_margins=(10, 20, 30, 40),
        )
        qtbot.addWidget(dlg)
        assert dlg.margins == (10.0, 20.0, 30.0, 40.0)


class TestSpinboxRanges:
    def test_top_bottom_capped_by_height(self, dialog: CropDialog) -> None:
        # Range upper bound is dim - 1
        assert dialog._top.maximum() == pytest.approx(791.0)
        assert dialog._bottom.maximum() == pytest.approx(791.0)

    def test_left_right_capped_by_width(self, dialog: CropDialog) -> None:
        assert dialog._left.maximum() == pytest.approx(611.0)
        assert dialog._right.maximum() == pytest.approx(611.0)


class TestReset:
    def test_reset_zeros_all_fields(self, dialog: CropDialog) -> None:
        dialog._top.setValue(50)
        dialog._right.setValue(50)
        dialog._bottom.setValue(50)
        dialog._left.setValue(50)
        dialog._reset()
        assert dialog.margins == (0.0, 0.0, 0.0, 0.0)


class TestMarginsOrder:
    def test_margins_order_is_top_right_bottom_left(self, dialog: CropDialog) -> None:
        dialog._top.setValue(1)
        dialog._right.setValue(2)
        dialog._bottom.setValue(3)
        dialog._left.setValue(4)
        assert dialog.margins == (1.0, 2.0, 3.0, 4.0)


class TestTitle:
    def test_title_uses_one_based_page(self, qtbot) -> None:
        dlg = CropDialog(page_index=4, page_width=612, page_height=792)
        qtbot.addWidget(dlg)
        # 0-based 4 -> 1-based "Page 5"
        assert "5" in dlg.windowTitle()

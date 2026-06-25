"""Tests for ExtractDialog."""

import pytest

from pdfprism.ui.dialogs.extract import ExtractDialog, ExtractKind


@pytest.fixture
def text_dialog(qtbot) -> ExtractDialog:
    d = ExtractDialog(page_count=3, kind=ExtractKind.TEXT)
    qtbot.addWidget(d)
    return d


@pytest.fixture
def images_dialog(qtbot) -> ExtractDialog:
    d = ExtractDialog(page_count=10, kind=ExtractKind.IMAGES)
    qtbot.addWidget(d)
    return d


class TestDefaults:
    def test_text_dialog_defaults_to_all_pages(self, text_dialog: ExtractDialog) -> None:
        assert text_dialog._all_radio.isChecked()
        assert not text_dialog._range_radio.isChecked()

    def test_default_range_is_full_document(self, text_dialog: ExtractDialog) -> None:
        assert text_dialog.page_range == range(0, 3)


class TestRangeSelection:
    def test_range_radio_enables_spinboxes(self, text_dialog: ExtractDialog) -> None:
        assert not text_dialog._from_spin.isEnabled()
        assert not text_dialog._to_spin.isEnabled()
        text_dialog._range_radio.setChecked(True)
        assert text_dialog._from_spin.isEnabled()
        assert text_dialog._to_spin.isEnabled()

    def test_range_returns_zero_based_half_open(self, text_dialog: ExtractDialog) -> None:
        text_dialog._range_radio.setChecked(True)
        text_dialog._from_spin.setValue(2)
        text_dialog._to_spin.setValue(3)
        # 1-based [2, 3] inclusive -> 0-based half-open [1, 3).
        assert text_dialog.page_range == range(1, 3)


class TestTitle:
    def test_images_kind_says_images(self, images_dialog: ExtractDialog) -> None:
        assert "image" in images_dialog.windowTitle().lower()

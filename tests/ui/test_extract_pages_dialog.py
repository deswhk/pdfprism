"""Tests for ExtractPagesDialog."""

from pathlib import Path

import pytest

from pdfprism.ui.dialogs.extract_pages import ExtractPagesDialog


@pytest.fixture
def dialog(tmp_path: Path, qtbot) -> ExtractPagesDialog:
    src = tmp_path / "doc.pdf"
    src.touch()  # path doesn't need to be a real PDF for dialog tests
    dlg = ExtractPagesDialog(source_path=src, page_count=10)
    qtbot.addWidget(dlg)
    return dlg


class TestDefaults:
    def test_default_range_is_full_document(self, dialog: ExtractPagesDialog) -> None:
        assert dialog.page_range == (0, 9)  # 0-based inclusive

    def test_default_output_path_has_pages_suffix(self, dialog: ExtractPagesDialog) -> None:
        path = dialog.output_path
        assert path.name == "doc_pages.pdf"


class TestRangeAdjustment:
    def test_change_from_spin(self, dialog: ExtractPagesDialog) -> None:
        dialog._from_spin.setValue(3)
        assert dialog.page_range == (2, 9)

    def test_change_to_spin(self, dialog: ExtractPagesDialog) -> None:
        dialog._to_spin.setValue(5)
        assert dialog.page_range == (0, 4)

    def test_from_above_to_drags_to(self, dialog: ExtractPagesDialog) -> None:
        # Set from to 7 first
        dialog._from_spin.setValue(7)
        # Then drop to below from
        dialog._to_spin.setValue(3)
        # from should drop to match
        assert dialog._from_spin.value() == 3

    def test_to_below_from_drags_from(self, dialog: ExtractPagesDialog) -> None:
        # Set to to 4 first
        dialog._to_spin.setValue(4)
        # Bump from above to
        dialog._from_spin.setValue(8)
        # to should jump up
        assert dialog._to_spin.value() == 8


class TestOkButtonEnabled:
    def test_disabled_when_output_path_empty(self, dialog: ExtractPagesDialog) -> None:
        from PySide6.QtWidgets import QDialogButtonBox

        dialog._output_edit.setText("")
        ok = dialog._button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok is not None
        assert ok.isEnabled() is False

    def test_enabled_when_output_path_set(self, dialog: ExtractPagesDialog) -> None:
        from PySide6.QtWidgets import QDialogButtonBox

        dialog._output_edit.setText("/tmp/out.pdf")
        ok = dialog._button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok is not None
        assert ok.isEnabled() is True


class TestTitle:
    def test_title(self, dialog: ExtractPagesDialog) -> None:
        assert dialog.windowTitle() == "Extract Pages to File"

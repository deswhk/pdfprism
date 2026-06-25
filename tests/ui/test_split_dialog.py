"""Tests for SplitDialog."""

from pathlib import Path

import pytest

from pdfprism.ui.dialogs.split import SplitDialog


@pytest.fixture
def dialog(tmp_path: Path, qtbot) -> SplitDialog:
    src = tmp_path / "doc.pdf"
    src.touch()
    dlg = SplitDialog(source_path=src, page_count=10)
    qtbot.addWidget(dlg)
    return dlg


class TestDefaults:
    def test_title(self, dialog: SplitDialog) -> None:
        assert dialog.windowTitle() == "Split Document"

    def test_default_mode_is_every(self, dialog: SplitDialog) -> None:
        assert dialog._every_radio.isChecked()
        assert dialog._at_radio.isChecked() is False

    def test_default_output_dir_is_source_parent(self, dialog: SplitDialog, tmp_path: Path) -> None:
        assert dialog.output_dir == tmp_path

    def test_stem_from_source(self, dialog: SplitDialog) -> None:
        assert dialog.stem == "doc"


class TestEveryNBreakpoints:
    def test_every_2_pages(self, dialog: SplitDialog) -> None:
        dialog._every_spin.setValue(2)
        dialog._on_accept()
        # 10 pages every 2 -> breakpoints at 2,4,6,8 -> 5 files of 2 each
        assert dialog.breakpoints == [2, 4, 6, 8]

    def test_every_3_pages(self, dialog: SplitDialog) -> None:
        dialog._every_spin.setValue(3)
        dialog._on_accept()
        # 10 pages every 3 -> breakpoints at 3,6,9 -> 4 files (3+3+3+1)
        assert dialog.breakpoints == [3, 6, 9]

    def test_every_1_page_per_file(self, dialog: SplitDialog) -> None:
        dialog._every_spin.setValue(1)
        dialog._on_accept()
        # 10 pages every 1 -> breakpoints 1..9
        assert dialog.breakpoints == [1, 2, 3, 4, 5, 6, 7, 8, 9]

    def test_every_greater_than_page_count_no_split(self, dialog: SplitDialog) -> None:
        dialog._every_spin.setValue(10)
        dialog._on_accept()
        # Splits at 10, but range(10, 10, 10) is empty
        assert dialog.breakpoints == []


class TestAtPagesBreakpoints:
    def test_valid_pages_parsed(self, dialog: SplitDialog) -> None:
        dialog._at_radio.setChecked(True)
        dialog._at_edit.setText("3, 7")
        dialog._on_accept()
        # 1-based to 0-based: 3->2, 7->6
        assert dialog.breakpoints == [2, 6]

    def test_extra_whitespace_ignored(self, dialog: SplitDialog) -> None:
        dialog._at_radio.setChecked(True)
        dialog._at_edit.setText("  3 ,  7  ")
        dialog._on_accept()
        assert dialog.breakpoints == [2, 6]

    def test_duplicates_collapsed(self, dialog: SplitDialog) -> None:
        dialog._at_radio.setChecked(True)
        dialog._at_edit.setText("3, 3, 7")
        dialog._on_accept()
        assert dialog.breakpoints == [2, 6]

    def test_unsorted_input_sorted(self, dialog: SplitDialog) -> None:
        dialog._at_radio.setChecked(True)
        dialog._at_edit.setText("7, 3")
        dialog._on_accept()
        assert dialog.breakpoints == [2, 6]

    def test_non_integer_keeps_dialog_open(self, dialog: SplitDialog, monkeypatch) -> None:
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
        dialog._at_radio.setChecked(True)
        dialog._at_edit.setText("3, foo, 7")
        dialog._on_accept()
        # accept() shouldn't have been called; dialog still ResultCode 0
        assert dialog.result() == 0

    def test_out_of_range_keeps_dialog_open(self, dialog: SplitDialog, monkeypatch) -> None:
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
        dialog._at_radio.setChecked(True)
        dialog._at_edit.setText("3, 99")
        dialog._on_accept()
        assert dialog.result() == 0

    def test_page_1_rejected(self, dialog: SplitDialog, monkeypatch) -> None:
        # Page 1 isn't a valid breakpoint (everything already starts there).
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
        dialog._at_radio.setChecked(True)
        dialog._at_edit.setText("1, 5")
        dialog._on_accept()
        assert dialog.result() == 0

    def test_empty_input_keeps_dialog_open(self, dialog: SplitDialog, monkeypatch) -> None:
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
        dialog._at_radio.setChecked(True)
        dialog._at_edit.setText("")
        dialog._on_accept()
        assert dialog.result() == 0


class TestOkButton:
    def test_disabled_when_output_dir_empty(self, dialog: SplitDialog) -> None:
        from PySide6.QtWidgets import QDialogButtonBox

        dialog._dir_edit.setText("")
        ok = dialog._button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok is not None
        assert ok.isEnabled() is False

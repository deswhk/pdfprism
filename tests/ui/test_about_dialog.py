"""Tests for AboutDialog."""

import pytest

from pdfprism.ui.dialogs.about import AboutDialog


@pytest.fixture
def dialog(qtbot) -> AboutDialog:
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    return dlg


class TestAbout:
    def test_title(self, dialog: AboutDialog) -> None:
        assert dialog.windowTitle() == "About pdfprism"

    def test_body_includes_version(self, dialog: AboutDialog) -> None:
        from PySide6.QtWidgets import QLabel

        import pdfprism

        labels = dialog.findChildren(QLabel)
        all_text = " ".join(lbl.text() for lbl in labels)
        assert pdfprism.__version__ in all_text

    def test_body_includes_license_and_source_links(self, dialog: AboutDialog) -> None:
        from PySide6.QtWidgets import QLabel

        labels = dialog.findChildren(QLabel)
        all_text = " ".join(lbl.text() for lbl in labels)
        assert "AGPL-3.0" in all_text
        assert "github.com/deswhk/pdfprism" in all_text

    def test_body_includes_warranty_disclaimer(self, dialog: AboutDialog) -> None:
        from PySide6.QtWidgets import QLabel

        labels = dialog.findChildren(QLabel)
        all_text = " ".join(lbl.text() for lbl in labels)
        assert "AS IS" in all_text

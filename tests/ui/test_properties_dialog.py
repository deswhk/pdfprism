"""Widget tests for PropertiesDialog (PR 11)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog

from pdfprism.ui.dialogs.properties import PropertiesDialog


@pytest.fixture
def empty_metadata() -> dict[str, str | None]:
    """A metadata dict where all six standard fields are None."""
    return {
        "title": None,
        "author": None,
        "subject": None,
        "keywords": None,
        "creator": None,
        "producer": None,
    }


@pytest.fixture
def full_metadata() -> dict[str, str | None]:
    """A metadata dict with all six fields populated."""
    return {
        "title": "Sample Title",
        "author": "Sample Author",
        "subject": "Sample Subject",
        "keywords": "one, two, three",
        "creator": "pdfprism",
        "producer": "PyMuPDF",
    }


# ---- Construction --------------------------------------------------------


class TestConstruction:
    def test_builds_with_empty_metadata(self, qtbot, empty_metadata: dict[str, str | None]) -> None:
        """Positive: dialog constructs when all metadata is None."""
        dlg = PropertiesDialog(empty_metadata)
        qtbot.addWidget(dlg)
        assert dlg is not None

    def test_builds_with_full_metadata(self, qtbot, full_metadata: dict[str, str | None]) -> None:
        """Positive: dialog constructs with populated fields."""
        dlg = PropertiesDialog(full_metadata)
        qtbot.addWidget(dlg)
        assert dlg is not None

    def test_window_title(self, qtbot, empty_metadata: dict[str, str | None]) -> None:
        """Positive: dialog title identifies its purpose."""
        dlg = PropertiesDialog(empty_metadata)
        qtbot.addWidget(dlg)
        assert dlg.windowTitle() == "Document Properties"


# ---- Field state ---------------------------------------------------------


class TestFieldState:
    def test_none_values_render_as_empty(
        self, qtbot, empty_metadata: dict[str, str | None]
    ) -> None:
        """Positive: None becomes empty text, not the string 'None'."""
        dlg = PropertiesDialog(empty_metadata)
        qtbot.addWidget(dlg)
        updates = dlg.get_updates()
        for key, value in updates.items():
            assert value == "", f"{key} shows {value!r} instead of empty"

    def test_initial_values_readable_via_get_updates(
        self, qtbot, full_metadata: dict[str, str | None]
    ) -> None:
        """Positive: what came in via constructor comes out via get_updates."""
        dlg = PropertiesDialog(full_metadata)
        qtbot.addWidget(dlg)
        updates = dlg.get_updates()
        for key, expected in full_metadata.items():
            assert updates[key] == expected

    def test_xmp_checkbox_default_checked(
        self, qtbot, empty_metadata: dict[str, str | None]
    ) -> None:
        """Positive: XMP-delete defaults to checked (safe default for sanitize)."""
        dlg = PropertiesDialog(empty_metadata)
        qtbot.addWidget(dlg)
        assert dlg.delete_xmp_requested is True


# ---- Sanitize button -----------------------------------------------------


class TestSanitizeButton:
    def test_clicking_sanitize_clears_all_fields(
        self, qtbot, full_metadata: dict[str, str | None]
    ) -> None:
        """Positive: Sanitize button clears every editor immediately."""
        dlg = PropertiesDialog(full_metadata)
        qtbot.addWidget(dlg)
        # Sanity check: fields are populated before click
        assert dlg.get_updates()["title"] == "Sample Title"
        # Simulate button click
        dlg._sanitize_button.click()
        # All fields should be empty now
        for key, value in dlg.get_updates().items():
            assert value == "", f"{key} not cleared after Sanitize"

    def test_sanitize_does_not_apply_until_ok(
        self, qtbot, full_metadata: dict[str, str | None]
    ) -> None:
        """Positive: after Sanitize the fields show empty but nothing is
        saved until the caller receives get_updates() via OK.

        Sanitize is a display/edit operation only. The caller decides
        whether to accept or cancel. This test just verifies that the
        editor state is consistent with what get_updates() reports.
        """
        dlg = PropertiesDialog(full_metadata)
        qtbot.addWidget(dlg)
        dlg._sanitize_button.click()
        # After Sanitize, all fields are empty.
        assert all(v == "" for v in dlg.get_updates().values())
        # User could now re-type into a field before OK:
        dlg._editors["title"].setText("Renamed")
        assert dlg.get_updates()["title"] == "Renamed"
        # Other fields still empty.
        assert dlg.get_updates()["author"] == ""


# ---- XMP checkbox --------------------------------------------------------


class TestXmpCheckbox:
    def test_toggle_updates_delete_xmp_requested(
        self, qtbot, empty_metadata: dict[str, str | None]
    ) -> None:
        """Positive: unchecking XMP flips delete_xmp_requested to False."""
        dlg = PropertiesDialog(empty_metadata)
        qtbot.addWidget(dlg)
        assert dlg.delete_xmp_requested is True
        dlg._delete_xmp.setChecked(False)
        assert dlg.delete_xmp_requested is False
        dlg._delete_xmp.setChecked(True)
        assert dlg.delete_xmp_requested is True


# ---- OK / Cancel ---------------------------------------------------------


class TestButtonBox:
    def test_accept_closes_dialog(self, qtbot, empty_metadata: dict[str, str | None]) -> None:
        """Positive: calling accept() sets DialogCode.Accepted."""
        dlg = PropertiesDialog(empty_metadata)
        qtbot.addWidget(dlg)
        dlg.accept()
        assert dlg.result() == QDialog.DialogCode.Accepted

    def test_reject_closes_dialog(self, qtbot, empty_metadata: dict[str, str | None]) -> None:
        """Positive: calling reject() sets DialogCode.Rejected."""
        dlg = PropertiesDialog(empty_metadata)
        qtbot.addWidget(dlg)
        dlg.reject()
        assert dlg.result() == QDialog.DialogCode.Rejected

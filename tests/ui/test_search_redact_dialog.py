"""Widget tests for SearchRedactDialog (PR 12.2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.types import SearchHit
from pdfprism.ui.dialogs.search_redact import SearchRedactDialog


@pytest.fixture
def dialog_with_mock_adapter(qtbot):
    """SearchRedactDialog with a MagicMock adapter (no real doc)."""
    adapter = MagicMock(spec=PyMuPDFAdapter)
    dlg = SearchRedactDialog(adapter)
    qtbot.addWidget(dlg)
    return dlg


class TestConstruction:
    def test_builds(self, dialog_with_mock_adapter: SearchRedactDialog) -> None:
        """Positive: dialog constructs with adapter."""
        assert dialog_with_mock_adapter is not None
        assert dialog_with_mock_adapter.windowTitle() == "Search and Redact"


class TestSearchFlow:
    def test_empty_term_shows_hint(self, dialog_with_mock_adapter: SearchRedactDialog) -> None:
        """Positive: searching with empty term shows a hint."""
        dialog_with_mock_adapter._term_input.setText("   ")
        dialog_with_mock_adapter._run_search()
        assert "enter a term" in dialog_with_mock_adapter._count_label.text().lower()
        assert dialog_with_mock_adapter._results.count() == 0

    def test_populates_results(self, dialog_with_mock_adapter: SearchRedactDialog) -> None:
        """Positive: search populates results with hit count."""
        fake_hits = [
            SearchHit(page_index=0, x0=0.0, y0=0.0, x1=10.0, y1=10.0),
            SearchHit(page_index=1, x0=0.0, y0=0.0, x1=10.0, y1=10.0),
            SearchHit(page_index=2, x0=0.0, y0=0.0, x1=10.0, y1=10.0),
        ]
        dialog_with_mock_adapter._term_input.setText("term")
        with patch.object(
            dialog_with_mock_adapter._search_service,
            "find_all",
            return_value=fake_hits,
        ):
            dialog_with_mock_adapter._run_search()

        assert dialog_with_mock_adapter._results.count() == 3
        assert "3 match(es)" in dialog_with_mock_adapter._count_label.text()

    def test_no_matches(self, dialog_with_mock_adapter: SearchRedactDialog) -> None:
        """Positive: no hits -> label reflects zero."""
        dialog_with_mock_adapter._term_input.setText("no_such_term")
        with patch.object(
            dialog_with_mock_adapter._search_service,
            "find_all",
            return_value=[],
        ):
            dialog_with_mock_adapter._run_search()

        assert dialog_with_mock_adapter._results.count() == 0
        assert "no matches" in dialog_with_mock_adapter._count_label.text().lower()


class TestSelection:
    def _populate(self, dlg: SearchRedactDialog, n: int) -> None:
        hits = [SearchHit(page_index=i, x0=0.0, y0=0.0, x1=10.0, y1=10.0) for i in range(n)]
        dlg._term_input.setText("t")
        with patch.object(dlg._search_service, "find_all", return_value=hits):
            dlg._run_search()

    def test_ok_button_label_reflects_count(
        self, dialog_with_mock_adapter: SearchRedactDialog
    ) -> None:
        """Positive: OK label shows count of selected items."""
        self._populate(dialog_with_mock_adapter, 3)
        assert "Redact 3 Selected" == dialog_with_mock_adapter._ok_button.text()
        # Uncheck first item
        dialog_with_mock_adapter._results.item(0).setCheckState(Qt.CheckState.Unchecked)
        assert "Redact 2 Selected" == dialog_with_mock_adapter._ok_button.text()

    def test_select_none_disables_ok(self, dialog_with_mock_adapter: SearchRedactDialog) -> None:
        """Positive: Select None disables OK, label says 0."""
        self._populate(dialog_with_mock_adapter, 2)
        dialog_with_mock_adapter._select_none()
        assert dialog_with_mock_adapter._ok_button.isEnabled() is False
        assert "0 Selected" in dialog_with_mock_adapter._ok_button.text()

    def test_select_all(self, dialog_with_mock_adapter: SearchRedactDialog) -> None:
        """Positive: Select All checks every item."""
        self._populate(dialog_with_mock_adapter, 4)
        dialog_with_mock_adapter._select_none()
        dialog_with_mock_adapter._select_all()
        for i in range(4):
            assert dialog_with_mock_adapter._results.item(i).checkState() == Qt.CheckState.Checked


class TestSelectedHits:
    def test_returns_only_checked_on_accept(
        self, dialog_with_mock_adapter: SearchRedactDialog
    ) -> None:
        """Positive: selected_hits() returns checked items after accept."""
        hits = [SearchHit(page_index=i, x0=0.0, y0=0.0, x1=10.0, y1=10.0) for i in range(3)]
        dialog_with_mock_adapter._term_input.setText("t")
        with patch.object(
            dialog_with_mock_adapter._search_service,
            "find_all",
            return_value=hits,
        ):
            dialog_with_mock_adapter._run_search()

        # Uncheck the middle one
        dialog_with_mock_adapter._results.item(1).setCheckState(Qt.CheckState.Unchecked)
        dialog_with_mock_adapter.accept()
        selected = dialog_with_mock_adapter.selected_hits()
        assert len(selected) == 2
        assert selected[0].page_index == 0
        assert selected[1].page_index == 2

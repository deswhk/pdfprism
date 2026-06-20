"""Tests for the DocumentView widget."""

from pathlib import Path

import pytest

from pdfprism.core.exceptions import PdfPrismError
from pdfprism.ui.widgets.document_view import DocumentView
from pdfprism.ui.widgets.page_view import ViewMode


@pytest.fixture
def document_view(sample_pdf_path: Path, qtbot) -> DocumentView:
    dv = DocumentView(sample_pdf_path)
    qtbot.addWidget(dv)
    return dv


class TestConstruction:
    def test_path_stored(self, sample_pdf_path: Path, qtbot) -> None:
        dv = DocumentView(sample_pdf_path)
        qtbot.addWidget(dv)
        assert dv.path == sample_pdf_path

    def test_not_opened_until_open_called(self, document_view: DocumentView) -> None:
        assert document_view.page_view.page_count == 0

    def test_initial_search_state_empty(self, document_view: DocumentView) -> None:
        assert document_view.search_hits == []
        assert document_view.current_hit_index == -1


class TestOpen:
    def test_open_loads_document(self, document_view: DocumentView) -> None:
        document_view.open()
        assert document_view.adapter.page_count == 3
        assert document_view.page_view.page_count == 3

    def test_open_garbage_raises(self, garbage_file: Path, qtbot) -> None:
        dv = DocumentView(garbage_file)
        qtbot.addWidget(dv)
        with pytest.raises(PdfPrismError):
            dv.open()


class TestClose:
    def test_close_clears_page_view(self, document_view: DocumentView) -> None:
        document_view.open()
        assert document_view.page_view.page_count == 3
        document_view.close_document()
        assert document_view.page_view.page_count == 0

    def test_close_is_idempotent(self, document_view: DocumentView) -> None:
        document_view.open()
        document_view.close_document()
        document_view.close_document()  # should not raise


class TestSignals:
    def test_page_changed_proxied(self, document_view: DocumentView, qtbot) -> None:
        document_view.open()
        with qtbot.waitSignal(document_view.page_changed, timeout=1000) as blocker:
            document_view.page_view.next_page()
        assert blocker.args == [1]

    def test_zoom_changed_proxied(self, document_view: DocumentView, qtbot) -> None:
        document_view.open()
        with qtbot.waitSignal(document_view.zoom_changed, timeout=1000):
            document_view.page_view.set_fit_width()

    def test_view_mode_changed_proxied(self, document_view: DocumentView, qtbot) -> None:
        document_view.open()
        with qtbot.waitSignal(document_view.view_mode_changed, timeout=1000) as blocker:
            document_view.page_view.set_view_mode(ViewMode.CONTINUOUS)
        assert blocker.args == [ViewMode.CONTINUOUS]

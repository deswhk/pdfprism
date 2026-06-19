"""Tests for PyMuPDFAdapter."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.document import DocumentAdapter
from pdfprism.core.exceptions import (
    DocumentOpenError,
    PageOutOfRangeError,
)
from pdfprism.core.types import DocumentInfo, OutlineItem, PageInfo

# PNG file signature
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def adapter() -> Iterator[PyMuPDFAdapter]:
    a = PyMuPDFAdapter()
    yield a
    a.close()


@pytest.fixture
def opened_adapter(adapter: PyMuPDFAdapter, sample_pdf_path: Path) -> PyMuPDFAdapter:
    adapter.open(sample_pdf_path)
    return adapter


def test_adapter_satisfies_protocol(adapter: PyMuPDFAdapter) -> None:
    assert isinstance(adapter, DocumentAdapter)


class TestOpen:
    def test_open_valid_pdf(self, opened_adapter: PyMuPDFAdapter) -> None:
        assert opened_adapter.page_count == 3

    def test_open_missing_file_raises(
        self, adapter: PyMuPDFAdapter, missing_pdf_path: Path
    ) -> None:
        with pytest.raises(DocumentOpenError, match="File not found"):
            adapter.open(missing_pdf_path)

    def test_open_garbage_raises(self, adapter: PyMuPDFAdapter, garbage_file: Path) -> None:
        with pytest.raises(DocumentOpenError):
            adapter.open(garbage_file)

    def test_open_second_document_closes_first(
        self, adapter: PyMuPDFAdapter, sample_pdf_path: Path
    ) -> None:
        adapter.open(sample_pdf_path)
        adapter.open(sample_pdf_path)
        assert adapter.page_count == 3


class TestPageCount:
    def test_page_count_without_open_raises(self, adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(DocumentOpenError, match="No document is currently open"):
            _ = adapter.page_count


class TestDocumentInfo:
    def test_metadata_fields(self, opened_adapter: PyMuPDFAdapter) -> None:
        info = opened_adapter.get_document_info()
        assert isinstance(info, DocumentInfo)
        assert info.page_count == 3
        assert info.title == "pdfprism sample"
        assert info.author == "deswhk"
        assert info.subject == "Test fixture"
        assert info.is_encrypted is False
        assert info.needs_password is False


class TestPageInfo:
    def test_first_page_dimensions(self, opened_adapter: PyMuPDFAdapter) -> None:
        info = opened_adapter.get_page_info(0)
        assert isinstance(info, PageInfo)
        assert info.index == 0
        assert info.width_points == pytest.approx(612.0)
        assert info.height_points == pytest.approx(792.0)

    def test_out_of_range_positive_raises(self, opened_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            opened_adapter.get_page_info(99)

    def test_out_of_range_negative_raises(self, opened_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            opened_adapter.get_page_info(-1)


class TestRenderPage:
    def test_returns_png_bytes(self, opened_adapter: PyMuPDFAdapter) -> None:
        png = opened_adapter.render_page(0)
        assert png.startswith(_PNG_MAGIC)
        assert len(png) > 100

    def test_higher_zoom_is_larger(self, opened_adapter: PyMuPDFAdapter) -> None:
        small = opened_adapter.render_page(0, zoom=1.0)
        large = opened_adapter.render_page(0, zoom=2.0)
        assert len(large) > len(small)

    def test_out_of_range_raises(self, opened_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            opened_adapter.render_page(99)


class TestClose:
    def test_close_without_open_is_noop(self) -> None:
        a = PyMuPDFAdapter()
        a.close()  # should not raise

    def test_close_is_idempotent(self, opened_adapter: PyMuPDFAdapter) -> None:
        opened_adapter.close()
        opened_adapter.close()


class TestGetOutline:
    def test_returns_outline_items(self, opened_adapter: PyMuPDFAdapter) -> None:
        outline = opened_adapter.get_outline()
        assert len(outline) == 4
        assert all(isinstance(item, OutlineItem) for item in outline)

    def test_first_chapter(self, opened_adapter: PyMuPDFAdapter) -> None:
        outline = opened_adapter.get_outline()
        assert outline[0] == OutlineItem(level=1, title="Chapter 1: Introduction", page_index=0)

    def test_subsection_entries(self, opened_adapter: PyMuPDFAdapter) -> None:
        outline = opened_adapter.get_outline()
        assert outline[1] == OutlineItem(level=2, title="1.1 Overview", page_index=0)
        assert outline[2] == OutlineItem(level=2, title="1.2 Background", page_index=1)

    def test_second_chapter(self, opened_adapter: PyMuPDFAdapter) -> None:
        outline = opened_adapter.get_outline()
        assert outline[3] == OutlineItem(level=1, title="Chapter 2: Conclusion", page_index=2)

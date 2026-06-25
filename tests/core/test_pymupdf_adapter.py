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
from pdfprism.core.types import DocumentInfo, OutlineItem, PageInfo, SearchHit

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


class TestSearch:
    def test_finds_known_term(self, opened_adapter: PyMuPDFAdapter) -> None:
        hits = opened_adapter.search_page(0, "pdfprism")
        assert len(hits) == 1
        assert isinstance(hits[0], SearchHit)
        assert hits[0].page_index == 0

    def test_finds_term_on_each_page(self, opened_adapter: PyMuPDFAdapter) -> None:
        # "Page" appears in "Page N of 3" on every page
        for i in range(3):
            hits = opened_adapter.search_page(i, "Page")
            assert len(hits) >= 1
            assert all(h.page_index == i for h in hits)

    def test_case_insensitive_matching(self, opened_adapter: PyMuPDFAdapter) -> None:
        upper = opened_adapter.search_page(0, "PAGE")
        lower = opened_adapter.search_page(0, "page")
        assert len(upper) == len(lower)
        assert len(upper) >= 1

    def test_missing_term_returns_empty(self, opened_adapter: PyMuPDFAdapter) -> None:
        assert opened_adapter.search_page(0, "thiswordisnotinthedoc") == []

    def test_empty_term_returns_empty(self, opened_adapter: PyMuPDFAdapter) -> None:
        assert opened_adapter.search_page(0, "") == []

    def test_out_of_range_raises(self, opened_adapter: PyMuPDFAdapter) -> None:
        with pytest.raises(PageOutOfRangeError):
            opened_adapter.search_page(99, "anything")

    def test_hit_rect_is_well_formed(self, opened_adapter: PyMuPDFAdapter) -> None:
        hits = opened_adapter.search_page(0, "pdfprism")
        assert len(hits) == 1
        h = hits[0]
        assert h.x0 > 0
        assert h.y0 > 0
        assert h.x1 > h.x0
        assert h.y1 > h.y0


class TestExtractWords:
    def test_extracts_words_on_first_page(self, sample_pdf_path: Path) -> None:
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            words = a.extract_words(0)
        finally:
            a.close()
        assert len(words) >= 3
        texts = [w.text for w in words]
        assert "Hello" in texts
        assert "pdfprism" in texts

    def test_word_has_positive_extent(self, sample_pdf_path: Path) -> None:
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            word = a.extract_words(0)[0]
        finally:
            a.close()
        assert word.x1 > word.x0
        assert word.y1 > word.y0

    def test_out_of_range_raises(self, sample_pdf_path: Path) -> None:
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            with pytest.raises(PageOutOfRangeError):
                a.extract_words(99)
        finally:
            a.close()

    def test_each_page_has_words(self, sample_pdf_path: Path) -> None:
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            for i in range(a.page_count):
                assert len(a.extract_words(i)) > 0
        finally:
            a.close()


class TestRotationProjection:
    """Rotation fix: search hits and extracted words land in layout space."""

    def test_rotated_page_hit_has_quad(self, sample_pdf_path: Path) -> None:
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            hits = a.search_page(2, "Page")
        finally:
            a.close()
        assert len(hits) == 1
        assert hits[0].quad is not None

    def test_rotated_hit_bbox_in_layout_space(self, sample_pdf_path: Path) -> None:
        """On a 90-rotated A4 page (layout 595x842), 'Page' should appear
        on the right edge (x ~490-510) rather than the upper-left where
        the unrotated coordinates would put it."""
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            hit = a.search_page(2, "Page")[0]
        finally:
            a.close()
        assert hit.x0 > 400, f"x0={hit.x0} should be on the right side of the rotated page"
        assert hit.x1 < 595
        assert hit.y0 < 200

    def test_unrotated_page_hit_quad_is_none(self, sample_pdf_path: Path) -> None:
        """Backward compat: rotation-0 hits leave quad as None."""
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            hits = a.search_page(0, "Page")
        finally:
            a.close()
        assert hits[0].quad is None

    def test_rotated_extract_words_in_layout_space(self, sample_pdf_path: Path) -> None:
        """extract_words projects through rotation_matrix so the slow
        path (case-sensitive / whole-word) hits also land correctly."""
        a = PyMuPDFAdapter()
        a.open(sample_pdf_path)
        try:
            words = a.extract_words(2)
        finally:
            a.close()
        page_words = [w for w in words if w.text == "Page"]
        assert len(page_words) == 1
        w = page_words[0]
        assert w.x0 > 400
        assert w.x1 < 595

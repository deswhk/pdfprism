"""Tests for ExtractService."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.services.extract import ExtractService, _join_words_as_lines


@pytest.fixture
def service(sample_pdf_path: Path) -> Iterator[ExtractService]:
    adapter = PyMuPDFAdapter()
    adapter.open(sample_pdf_path)
    yield ExtractService(adapter)
    adapter.close()


@pytest.fixture
def adapter(sample_pdf_path: Path) -> Iterator[PyMuPDFAdapter]:
    a = PyMuPDFAdapter()
    a.open(sample_pdf_path)
    yield a
    a.close()


class TestTextForPage:
    def test_returns_page_text(self, service: ExtractService) -> None:
        assert service.text_for_page(0) == "Hello from pdfprism\nPage 1 of 3\n"

    def test_every_page_extractable(self, service: ExtractService) -> None:
        for i in range(3):
            assert "Page" in service.text_for_page(i)


class TestTextFullDocument:
    def test_default_is_all_pages_with_form_feed(self, service: ExtractService) -> None:
        text = service.text_full_document()
        assert text.count("\f") == 2  # 3 pages -> 2 separators

    def test_explicit_range_extracts_only_those_pages(self, service: ExtractService) -> None:
        text = service.text_full_document(page_range=range(0, 2))
        assert text.count("\f") == 1
        assert "Page 1" in text
        assert "Page 2" in text
        assert "Page 3" not in text

    def test_single_page_range_has_no_form_feed(self, service: ExtractService) -> None:
        text = service.text_full_document(page_range=range(1, 2))
        assert "\f" not in text
        assert "Page 2" in text


class TestTextInRect:
    def test_tight_rect_returns_single_word(
        self, service: ExtractService, adapter: PyMuPDFAdapter
    ) -> None:
        words = adapter.extract_words(0)
        hello = next(w for w in words if w.text == "Hello")
        rect = (hello.x0 - 1, hello.y0 - 1, hello.x1 + 1, hello.y1 + 1)
        assert service.text_in_rect(0, rect) == "Hello"

    def test_empty_rect_returns_empty(self, service: ExtractService) -> None:
        # Rect far outside any text on the page.
        assert service.text_in_rect(0, (9000.0, 9000.0, 9001.0, 9001.0)) == ""

    def test_full_page_rect_returns_all_words(self, service: ExtractService) -> None:
        text = service.text_in_rect(0, (0.0, 0.0, 10000.0, 10000.0))
        assert "Hello" in text
        assert "pdfprism" in text


class TestSnippetAround:
    def test_short_line_returned_in_full(
        self, service: ExtractService, adapter: PyMuPDFAdapter
    ) -> None:
        words = adapter.extract_words(0)
        page_w = next(w for w in words if w.text == "Page")
        snippet = service.snippet_around(0, (page_w.x0, page_w.y0, page_w.x1, page_w.y1))
        # Default max_chars=80; "Page 1 of 3" fits, so the whole line returns.
        assert "Page 1 of 3" in snippet

    def test_no_words_returns_empty(self, service: ExtractService) -> None:
        assert service.snippet_around(0, (9000.0, 9000.0, 9001.0, 9001.0)) == ""

    def test_max_chars_trims_with_ellipses(
        self, service: ExtractService, adapter: PyMuPDFAdapter
    ) -> None:
        words = adapter.extract_words(0)
        # Use any word's rect; max_chars=3 forces trimming.
        w = words[0]
        snippet = service.snippet_around(0, (w.x0, w.y0, w.x1, w.y1), max_chars=3)
        # Either side may be trimmed; ellipses appear when trimmed.
        assert "..." in snippet or len(snippet) <= 3


class TestImagesFullDocument:
    def test_text_only_writes_no_files(self, service: ExtractService, tmp_path: Path) -> None:
        out = tmp_path / "img-out"
        written = service.images_full_document(out)
        assert written == []
        # Directory was still created.
        assert out.is_dir()

    def test_creates_output_dir(self, service: ExtractService, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "deeper"
        assert not out.exists()
        service.images_full_document(out)
        assert out.is_dir()


class TestJoinWordsAsLines:
    def test_empty_words_returns_empty(self) -> None:
        assert _join_words_as_lines([]) == ""

    def test_single_word(self, adapter: PyMuPDFAdapter) -> None:
        words = adapter.extract_words(0)
        assert _join_words_as_lines([words[0]]) == words[0].text

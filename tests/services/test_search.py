"""Tests for SearchService."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.types import CrossDocHit, SearchHit
from pdfprism.services.search import SearchService


@pytest.fixture
def service(sample_pdf_path: Path) -> Iterator[SearchService]:
    adapter = PyMuPDFAdapter()
    adapter.open(sample_pdf_path)
    yield SearchService(adapter)
    adapter.close()


class TestFindAll:
    def test_returns_hits_across_document(self, service: SearchService) -> None:
        hits = service.find_all("Page")
        assert len(hits) >= 3
        assert {h.page_index for h in hits} == {0, 1, 2}

    def test_hits_in_document_order(self, service: SearchService) -> None:
        hits = service.find_all("Page")
        page_indices = [h.page_index for h in hits]
        assert page_indices == sorted(page_indices)

    def test_returns_search_hit_instances(self, service: SearchService) -> None:
        hits = service.find_all("pdfprism")
        assert len(hits) >= 1
        assert all(isinstance(h, SearchHit) for h in hits)

    def test_missing_term_returns_empty(self, service: SearchService) -> None:
        assert service.find_all("thiswordisnotinthedoc") == []

    def test_empty_term_returns_empty(self, service: SearchService) -> None:
        assert service.find_all("") == []


@pytest.fixture
def two_adapters(sample_pdf_path: Path) -> Iterator[list[PyMuPDFAdapter]]:
    """Two open adapters on the same fixture for cross-doc tests."""
    a1 = PyMuPDFAdapter()
    a1.open(sample_pdf_path)
    a2 = PyMuPDFAdapter()
    a2.open(sample_pdf_path)
    yield [a1, a2]
    a1.close()
    a2.close()


class TestFindAllAcross:
    def test_walks_multiple_documents(self, two_adapters: list[PyMuPDFAdapter]) -> None:
        results = SearchService.find_all_across(two_adapters, "Page")
        doc_indices = {r.doc_index for r in results}
        assert doc_indices == {0, 1}

    def test_doc_0_hits_before_doc_1_hits(self, two_adapters: list[PyMuPDFAdapter]) -> None:
        results = SearchService.find_all_across(two_adapters, "Page")
        doc_indices = [r.doc_index for r in results]
        assert doc_indices == sorted(doc_indices)

    def test_page_order_within_each_doc(self, two_adapters: list[PyMuPDFAdapter]) -> None:
        results = SearchService.find_all_across(two_adapters, "Page")
        per_doc_pages: dict[int, list[int]] = {}
        for r in results:
            per_doc_pages.setdefault(r.doc_index, []).append(r.hit.page_index)
        for pages in per_doc_pages.values():
            assert pages == sorted(pages)

    def test_empty_term_returns_empty(self, two_adapters: list[PyMuPDFAdapter]) -> None:
        assert SearchService.find_all_across(two_adapters, "") == []

    def test_empty_adapter_list_returns_empty(self) -> None:
        assert SearchService.find_all_across([], "anything") == []

    def test_no_match_term_returns_empty(self, two_adapters: list[PyMuPDFAdapter]) -> None:
        results = SearchService.find_all_across(two_adapters, "thiswordisnotinthedoc")
        assert results == []

    def test_cross_doc_hit_carries_hit_fields(self, two_adapters: list[PyMuPDFAdapter]) -> None:
        results = SearchService.find_all_across(two_adapters, "Page")
        assert len(results) >= 1
        first = results[0]
        assert isinstance(first, CrossDocHit)
        assert first.doc_index in (0, 1)
        assert isinstance(first.hit, SearchHit)
        assert first.hit.page_index >= 0


class TestFindAllSlowPath:
    def test_case_sensitive_finds_capitalized(self, service):
        hits = service.find_all("Hello", case_sensitive=True)
        assert len(hits) >= 1

    def test_case_sensitive_rejects_wrong_case(self, service):
        hits = service.find_all("hello", case_sensitive=True)
        assert hits == []

    def test_case_insensitive_finds_either_case(self, service):
        upper = service.find_all("HELLO")
        lower = service.find_all("hello")
        assert len(upper) == len(lower) >= 1

    def test_whole_word_finds_standalone(self, service):
        hits = service.find_all("pdfprism", whole_word=True)
        assert len(hits) >= 1

    def test_whole_word_rejects_substring(self, service):
        hits = service.find_all("pdf", whole_word=True)
        assert hits == []

    def test_substring_does_match_pdf(self, service):
        hits = service.find_all("pdf")
        assert len(hits) >= 1

    def test_combined_case_and_whole_word(self, service):
        good = service.find_all("Page", case_sensitive=True, whole_word=True)
        bad = service.find_all("page", case_sensitive=True, whole_word=True)
        assert len(good) >= 1
        assert bad == []

    def test_slow_path_empty_term_returns_empty(self, service):
        assert service.find_all("", case_sensitive=True) == []
        assert service.find_all("", whole_word=True) == []


class TestFindAllAcrossSlowPath:
    def test_case_sensitive_across_docs(self, sample_pdf_path: Path) -> None:
        a1 = PyMuPDFAdapter()
        a1.open(sample_pdf_path)
        a2 = PyMuPDFAdapter()
        a2.open(sample_pdf_path)
        try:
            hits = SearchService.find_all_across([a1, a2], "Hello", case_sensitive=True)
            assert len(hits) >= 2
            assert {h.doc_index for h in hits} == {0, 1}
        finally:
            a1.close()
            a2.close()

    def test_whole_word_across_docs_rejects_substring(self, sample_pdf_path: Path) -> None:
        a1 = PyMuPDFAdapter()
        a1.open(sample_pdf_path)
        a2 = PyMuPDFAdapter()
        a2.open(sample_pdf_path)
        try:
            hits = SearchService.find_all_across([a1, a2], "pdf", whole_word=True)
            assert hits == []
        finally:
            a1.close()
            a2.close()

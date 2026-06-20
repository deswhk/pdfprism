"""Tests for SearchService."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.types import SearchHit
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

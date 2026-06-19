"""Tests for PageCache."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtGui import QPixmap

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.ui.page_cache import PageCache


@pytest.fixture
def adapter_with_doc(sample_pdf_path: Path) -> Iterator[PyMuPDFAdapter]:
    a = PyMuPDFAdapter()
    a.open(sample_pdf_path)
    yield a
    a.close()


class TestEmpty:
    def test_empty_cache_size_zero(self) -> None:
        cache = PageCache()
        assert cache.size == 0

    def test_get_miss_returns_none(self) -> None:
        cache = PageCache()
        assert cache.get(0, 1.0) is None

    def test_render_without_adapter_returns_empty_pixmap(self) -> None:
        cache = PageCache()
        pix = cache.get_or_render(0, 1.0)
        assert isinstance(pix, QPixmap)
        assert pix.isNull()


class TestRendering:
    def test_get_or_render_populates_cache(self, adapter_with_doc: PyMuPDFAdapter) -> None:
        cache = PageCache(adapter_with_doc)
        pix = cache.get_or_render(0, 1.0)
        assert isinstance(pix, QPixmap)
        assert not pix.isNull()
        assert cache.size == 1

    def test_cache_hit_does_not_re_render(self, adapter_with_doc: PyMuPDFAdapter) -> None:
        cache = PageCache(adapter_with_doc)
        first = cache.get_or_render(0, 1.0)
        again = cache.get(0, 1.0)
        assert again is first

    def test_different_zoom_is_different_entry(self, adapter_with_doc: PyMuPDFAdapter) -> None:
        cache = PageCache(adapter_with_doc)
        cache.get_or_render(0, 1.0)
        cache.get_or_render(0, 2.0)
        assert cache.size == 2


class TestEviction:
    def test_lru_eviction(self, adapter_with_doc: PyMuPDFAdapter) -> None:
        cache = PageCache(adapter_with_doc, max_entries=2)
        cache.get_or_render(0, 1.0)
        cache.get_or_render(1, 1.0)
        assert cache.size == 2
        cache.get_or_render(2, 1.0)
        assert cache.size == 2
        assert cache.get(0, 1.0) is None
        assert cache.get(1, 1.0) is not None
        assert cache.get(2, 1.0) is not None

    def test_access_promotes_to_most_recent(self, adapter_with_doc: PyMuPDFAdapter) -> None:
        cache = PageCache(adapter_with_doc, max_entries=2)
        cache.get_or_render(0, 1.0)
        cache.get_or_render(1, 1.0)
        cache.get(0, 1.0)  # promote page 0
        cache.get_or_render(2, 1.0)
        assert cache.get(0, 1.0) is not None
        assert cache.get(1, 1.0) is None
        assert cache.get(2, 1.0) is not None


class TestAdapterRebind:
    def test_set_adapter_clears_cache(self, adapter_with_doc: PyMuPDFAdapter) -> None:
        cache = PageCache(adapter_with_doc)
        cache.get_or_render(0, 1.0)
        assert cache.size == 1
        cache.set_adapter(None)
        assert cache.size == 0

    def test_clear(self, adapter_with_doc: PyMuPDFAdapter) -> None:
        cache = PageCache(adapter_with_doc)
        cache.get_or_render(0, 1.0)
        cache.get_or_render(1, 1.0)
        cache.clear()
        assert cache.size == 0

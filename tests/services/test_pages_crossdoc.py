"""Tests for cross-document operations in services/pages.py.

Covers PageService.extract_to_file, .insert_from, .split, and the free
function merge(). All four operations build on the adapter's
new_document + insert_pdf primitives; these tests verify the service-
layer composition and edge cases.
"""

from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.exceptions import PageOperationError, PageOutOfRangeError
from pdfprism.services.pages import PageService, merge

# ---- Fixtures -------------------------------------------------------------


def _build_pdf(path: Path, n_pages: int, tag: str) -> Path:
    """Build an N-page PDF with identifiable text on each page."""
    d = pymupdf.open()
    for i in range(n_pages):
        p = d.new_page(width=100, height=100)
        p.insert_text((10, 10), f"{tag}-{i}")
    d.save(str(path))
    d.close()
    return path


@pytest.fixture
def small_pdf(tmp_path: Path) -> Path:
    return _build_pdf(tmp_path / "small.pdf", 3, "S")


@pytest.fixture
def big_pdf(tmp_path: Path) -> Path:
    return _build_pdf(tmp_path / "big.pdf", 7, "B")


@pytest.fixture
def service(big_pdf: Path) -> Iterator[PageService]:
    a = PyMuPDFAdapter()
    a.open(big_pdf)
    yield PageService(a)
    a.close()


# ---- TestExtractToFile ----------------------------------------------------


class TestExtractToFile:
    def test_extracts_requested_range(self, service: PageService, tmp_path: Path) -> None:
        out = tmp_path / "extracted.pdf"
        service.extract_to_file(2, 4, out)
        verifier = PyMuPDFAdapter()
        verifier.open(out)
        try:
            assert verifier.page_count == 3
            assert "B-2" in verifier.extract_text(0)
            assert "B-4" in verifier.extract_text(2)
        finally:
            verifier.close()

    def test_source_unchanged(self, service: PageService, tmp_path: Path, big_pdf: Path) -> None:
        before = service._adapter.page_count
        service.extract_to_file(0, 2, tmp_path / "out.pdf")
        assert service._adapter.page_count == before
        assert service._adapter.is_dirty is False

    def test_out_of_range_raises(self, service: PageService, tmp_path: Path) -> None:
        with pytest.raises(PageOutOfRangeError):
            service.extract_to_file(0, 99, tmp_path / "out.pdf")

    def test_single_page(self, service: PageService, tmp_path: Path) -> None:
        out = tmp_path / "one.pdf"
        service.extract_to_file(3, 3, out)
        verifier = PyMuPDFAdapter()
        verifier.open(out)
        try:
            assert verifier.page_count == 1
        finally:
            verifier.close()


# ---- TestInsertFrom -------------------------------------------------------


class TestInsertFrom:
    def test_inserts_at_position(self, service: PageService, small_pdf: Path) -> None:
        # big has 7 pages, insert 3 pages from small at position 2
        before = service._adapter.page_count
        service.insert_from(small_pdf, 0, 2, 2)
        assert service._adapter.page_count == before + 3
        assert service._adapter.is_dirty is True

    def test_inserts_partial_range(self, service: PageService, small_pdf: Path) -> None:
        before = service._adapter.page_count
        service.insert_from(small_pdf, 1, 2, 0)
        assert service._adapter.page_count == before + 2

    def test_append_at_end(self, service: PageService, small_pdf: Path) -> None:
        before = service._adapter.page_count
        service.insert_from(small_pdf, 0, 2, before)
        assert service._adapter.page_count == before + 3

    def test_invalid_source_path_raises(self, service: PageService, tmp_path: Path) -> None:
        from pdfprism.core.exceptions import DocumentOpenError

        with pytest.raises(DocumentOpenError):
            service.insert_from(tmp_path / "nonexistent.pdf", 0, 0, 0)


# ---- TestSplit ------------------------------------------------------------


class TestSplit:
    def test_split_at_one_breakpoint(self, service: PageService, tmp_path: Path) -> None:
        # 7 pages, split at [3] -> 3-page file + 4-page file
        out_dir = tmp_path / "split"
        out_dir.mkdir()
        paths = service.split([3], out_dir, "doc")
        assert len(paths) == 2
        assert all(p.exists() for p in paths)
        sizes = []
        for p in paths:
            v = PyMuPDFAdapter()
            v.open(p)
            try:
                sizes.append(v.page_count)
            finally:
                v.close()
        assert sizes == [3, 4]

    def test_split_multiple_breakpoints(self, service: PageService, tmp_path: Path) -> None:
        # 7 pages, split at [2, 5] -> 2 + 3 + 2 pages
        out_dir = tmp_path / "split"
        out_dir.mkdir()
        paths = service.split([2, 5], out_dir, "doc")
        assert len(paths) == 3
        sizes = []
        for p in paths:
            v = PyMuPDFAdapter()
            v.open(p)
            try:
                sizes.append(v.page_count)
            finally:
                v.close()
        assert sizes == [2, 3, 2]

    def test_naming_zero_pads_to_largest_digit_count(
        self, service: PageService, tmp_path: Path
    ) -> None:
        # 7 pages, breakpoints [1,2,3,4,5,6] -> 7 single-page files;
        # need width=1 (largest N is 7). Verify naming.
        out_dir = tmp_path / "split"
        out_dir.mkdir()
        paths = service.split([1, 2, 3, 4, 5, 6], out_dir, "p")
        names = [p.name for p in paths]
        assert names == [f"p-{i}.pdf" for i in range(1, 8)]

    def test_naming_zero_pads_when_double_digit(self, service: PageService, tmp_path: Path) -> None:
        # 7 pages -> can produce only up to 7 outputs. Make a wider doc.
        wider = tmp_path / "wider.pdf"
        _build_pdf(wider, 12, "W")
        a = PyMuPDFAdapter()
        a.open(wider)
        try:
            svc = PageService(a)
            out_dir = tmp_path / "wsplit"
            out_dir.mkdir()
            paths = svc.split(list(range(1, 12)), out_dir, "p")
            names = [p.name for p in paths]
            # Largest N = 12, so width = 2; names like "p-01.pdf"
            assert names[0] == "p-01.pdf"
            assert names[-1] == "p-12.pdf"
        finally:
            a.close()

    def test_out_of_range_breakpoints_silently_skipped(
        self, service: PageService, tmp_path: Path
    ) -> None:
        # 7 pages, breakpoints [3, 99] -> 99 is silently dropped
        out_dir = tmp_path / "split"
        out_dir.mkdir()
        paths = service.split([3, 99], out_dir, "doc")
        # Same result as [3] alone
        assert len(paths) == 2

    def test_no_breakpoints_returns_single_file(self, service: PageService, tmp_path: Path) -> None:
        out_dir = tmp_path / "split"
        out_dir.mkdir()
        paths = service.split([], out_dir, "doc")
        assert len(paths) == 1
        v = PyMuPDFAdapter()
        v.open(paths[0])
        try:
            assert v.page_count == 7
        finally:
            v.close()

    def test_source_unchanged(self, service: PageService, tmp_path: Path) -> None:
        before = service._adapter.page_count
        out_dir = tmp_path / "split"
        out_dir.mkdir()
        service.split([3], out_dir, "doc")
        assert service._adapter.page_count == before
        assert service._adapter.is_dirty is False


# ---- Test merge (free function) -------------------------------------------


class TestMerge:
    def test_merges_two_sources_in_order(
        self, small_pdf: Path, big_pdf: Path, tmp_path: Path
    ) -> None:
        a = PyMuPDFAdapter()
        b = PyMuPDFAdapter()
        a.open(big_pdf)
        b.open(small_pdf)
        try:
            out = tmp_path / "merged.pdf"
            merge([a, b], out)
            v = PyMuPDFAdapter()
            v.open(out)
            try:
                # big (7) + small (3) = 10
                assert v.page_count == 10
                assert "B-0" in v.extract_text(0)
                assert "S-0" in v.extract_text(7)
            finally:
                v.close()
        finally:
            a.close()
            b.close()

    def test_order_matters(self, small_pdf: Path, big_pdf: Path, tmp_path: Path) -> None:
        a = PyMuPDFAdapter()
        b = PyMuPDFAdapter()
        a.open(big_pdf)
        b.open(small_pdf)
        try:
            out = tmp_path / "merged.pdf"
            merge([b, a], out)  # small first
            v = PyMuPDFAdapter()
            v.open(out)
            try:
                assert "S-0" in v.extract_text(0)
                assert "B-0" in v.extract_text(3)
            finally:
                v.close()
        finally:
            a.close()
            b.close()

    def test_sources_unchanged(self, small_pdf: Path, big_pdf: Path, tmp_path: Path) -> None:
        a = PyMuPDFAdapter()
        b = PyMuPDFAdapter()
        a.open(big_pdf)
        b.open(small_pdf)
        try:
            merge([a, b], tmp_path / "merged.pdf")
            assert a.is_dirty is False
            assert b.is_dirty is False
        finally:
            a.close()
            b.close()

    def test_single_source_raises(self, small_pdf: Path, tmp_path: Path) -> None:
        a = PyMuPDFAdapter()
        a.open(small_pdf)
        try:
            with pytest.raises(PageOperationError, match="at least two"):
                merge([a], tmp_path / "out.pdf")
        finally:
            a.close()

    def test_empty_list_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PageOperationError, match="at least two"):
            merge([], tmp_path / "out.pdf")

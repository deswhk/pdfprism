"""Tests for PageService."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.services.pages import PageService


@pytest.fixture
def service(mutable_pdf_path: Path) -> Iterator[PageService]:
    adapter = PyMuPDFAdapter()
    adapter.open(mutable_pdf_path)
    yield PageService(adapter)
    adapter.close()


@pytest.fixture
def adapter_and_service(
    mutable_pdf_path: Path,
) -> Iterator[tuple[PyMuPDFAdapter, PageService]]:
    """Some tests need to inspect the adapter directly."""
    a = PyMuPDFAdapter()
    a.open(mutable_pdf_path)
    yield a, PageService(a)
    a.close()


class TestRotation:
    def test_rotate_right_adds_90(
        self, adapter_and_service: tuple[PyMuPDFAdapter, PageService]
    ) -> None:
        a, svc = adapter_and_service
        before = a.get_page_info(0).rotation
        svc.rotate_right(0)
        assert (a.get_page_info(0).rotation - before) % 360 == 90

    def test_rotate_left_adds_270(
        self, adapter_and_service: tuple[PyMuPDFAdapter, PageService]
    ) -> None:
        a, svc = adapter_and_service
        before = a.get_page_info(0).rotation
        svc.rotate_left(0)
        assert (a.get_page_info(0).rotation - before) % 360 == 270

    def test_rotate_page_passes_degrees(
        self, adapter_and_service: tuple[PyMuPDFAdapter, PageService]
    ) -> None:
        a, svc = adapter_and_service
        before = a.get_page_info(0).rotation
        svc.rotate_page(0, 180)
        assert (a.get_page_info(0).rotation - before) % 360 == 180


class TestDelete:
    def test_delete_page_single(
        self, adapter_and_service: tuple[PyMuPDFAdapter, PageService]
    ) -> None:
        a, svc = adapter_and_service
        before = a.page_count
        svc.delete_page(0)
        assert a.page_count == before - 1

    def test_delete_pages_accepts_iterable(
        self, adapter_and_service: tuple[PyMuPDFAdapter, PageService]
    ) -> None:
        a, svc = adapter_and_service
        before = a.page_count
        svc.delete_pages(iter([0, 1]))  # any iterable, not just list
        assert a.page_count == before - 2


class TestInsert:
    def test_insert_blank_page_after(
        self, adapter_and_service: tuple[PyMuPDFAdapter, PageService]
    ) -> None:
        a, svc = adapter_and_service
        before = a.page_count
        svc.insert_blank_page_after(0, 100, 100)
        assert a.page_count == before + 1
        # The new page lives at index 1 (after the 0th).
        assert a.get_page_info(1).width_points == 100

    def test_insert_blank_page_before(
        self, adapter_and_service: tuple[PyMuPDFAdapter, PageService]
    ) -> None:
        a, svc = adapter_and_service
        before = a.page_count
        svc.insert_blank_page_before(1, 100, 100)
        assert a.page_count == before + 1
        assert a.get_page_info(1).width_points == 100

    def test_append_blank_page(
        self, adapter_and_service: tuple[PyMuPDFAdapter, PageService]
    ) -> None:
        a, svc = adapter_and_service
        before = a.page_count
        svc.append_blank_page(50, 70)
        assert a.page_count == before + 1
        last = a.get_page_info(before)
        assert last.width_points == 50
        assert last.height_points == 70


class TestDuplicateAndMove:
    def test_duplicate_page(self, adapter_and_service: tuple[PyMuPDFAdapter, PageService]) -> None:
        a, svc = adapter_and_service
        before = a.page_count
        svc.duplicate_page(0)
        assert a.page_count == before + 1
        assert a.extract_text(0) == a.extract_text(1)

    def test_move_page(self, adapter_and_service: tuple[PyMuPDFAdapter, PageService]) -> None:
        a, svc = adapter_and_service
        t0 = a.extract_text(0)
        last = a.page_count - 1
        svc.move_page(0, last)
        assert a.extract_text(last) == t0


class TestCrop:
    def test_crop_page_applies_margins(
        self, adapter_and_service: tuple[PyMuPDFAdapter, PageService]
    ) -> None:
        a, svc = adapter_and_service
        info = a.get_page_info(0)
        svc.crop_page(0, (5, 5, 5, 5))
        cb = a._doc[0].cropbox
        assert abs((cb.x1 - cb.x0) - (info.width_points - 10)) < 0.01
        assert abs((cb.y1 - cb.y0) - (info.height_points - 10)) < 0.01

    def test_crop_zero_clears(
        self, adapter_and_service: tuple[PyMuPDFAdapter, PageService]
    ) -> None:
        a, svc = adapter_and_service
        info = a.get_page_info(0)
        svc.crop_page(0, (10, 10, 10, 10))
        svc.crop_page(0, (0, 0, 0, 0))
        cb = a._doc[0].cropbox
        assert abs((cb.x1 - cb.x0) - info.width_points) < 0.01

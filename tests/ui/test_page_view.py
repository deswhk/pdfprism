"""Tests for the PageView widget."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.ui.page_cache import PageCache
from pdfprism.ui.widgets.page_view import PageView, ZoomMode


@pytest.fixture
def page_view(qtbot) -> PageView:
    cache = PageCache()
    widget = PageView(cache)
    widget.resize(800, 600)
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def adapter_with_doc(sample_pdf_path: Path) -> Iterator[PyMuPDFAdapter]:
    a = PyMuPDFAdapter()
    a.open(sample_pdf_path)
    yield a
    a.close()


class TestEmpty:
    def test_no_pages_initially(self, page_view: PageView) -> None:
        assert page_view.page_count == 0
        assert page_view.current_page == 0
        assert page_view.zoom_mode == ZoomMode.FIT_PAGE

    def test_navigation_noop_without_doc(self, page_view: PageView) -> None:
        page_view.next_page()
        page_view.prev_page()
        page_view.first_page()
        page_view.last_page()
        page_view.go_to_page(0)
        assert page_view.current_page == 0
        assert page_view.page_count == 0


class TestBinding:
    def test_set_adapter_renders_first_page(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        assert page_view.page_count == 3
        assert page_view.current_page == 0

    def test_clear_resets_state(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.next_page()
        page_view.clear()
        assert page_view.page_count == 0
        assert page_view.current_page == 0


class TestNavigation:
    def test_next_page(self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.next_page()
        assert page_view.current_page == 1

    def test_prev_at_first_is_noop(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.prev_page()
        assert page_view.current_page == 0

    def test_next_at_last_is_noop(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.last_page()
        assert page_view.current_page == 2
        page_view.next_page()
        assert page_view.current_page == 2

    def test_first_and_last(self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.last_page()
        assert page_view.current_page == 2
        page_view.first_page()
        assert page_view.current_page == 0

    def test_go_to_page(self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.go_to_page(2)
        assert page_view.current_page == 2

    def test_go_to_page_out_of_range_is_noop(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.go_to_page(99)
        assert page_view.current_page == 0
        page_view.go_to_page(-1)
        assert page_view.current_page == 0

    def test_go_to_current_page_is_noop(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.go_to_page(1)
        page_view.go_to_page(1)
        assert page_view.current_page == 1


class TestZoomModes:
    def test_set_fit_page(self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.set_fit_page()
        assert page_view.zoom_mode == ZoomMode.FIT_PAGE

    def test_set_fit_width(self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.set_fit_width()
        assert page_view.zoom_mode == ZoomMode.FIT_WIDTH

    def test_set_actual_size(self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.set_actual_size()
        assert page_view.zoom_mode == ZoomMode.ACTUAL_SIZE

    def test_set_custom_zoom(self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.set_custom_zoom(1.5)
        assert page_view.zoom_mode == ZoomMode.CUSTOM

    def test_custom_zoom_clamped_to_bounds(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.set_custom_zoom(100.0)
        assert page_view.zoom_mode == ZoomMode.CUSTOM
        page_view.set_custom_zoom(0.001)
        assert page_view.zoom_mode == ZoomMode.CUSTOM

    def test_zoom_in_changes_mode_to_custom(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.set_fit_page()
        page_view.zoom_in()
        assert page_view.zoom_mode == ZoomMode.CUSTOM


class TestSignals:
    def test_page_changed_emitted_on_set_adapter(
        self,
        page_view: PageView,
        adapter_with_doc: PyMuPDFAdapter,
        qtbot,
    ) -> None:
        with qtbot.waitSignal(page_view.page_changed, timeout=1000) as blocker:
            page_view.set_adapter(adapter_with_doc)
        assert blocker.args == [0]

    def test_page_changed_emitted_on_next(
        self,
        page_view: PageView,
        adapter_with_doc: PyMuPDFAdapter,
        qtbot,
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        with qtbot.waitSignal(page_view.page_changed, timeout=1000) as blocker:
            page_view.next_page()
        assert blocker.args == [1]

    def test_zoom_changed_emitted_on_mode_change(
        self,
        page_view: PageView,
        adapter_with_doc: PyMuPDFAdapter,
        qtbot,
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        with qtbot.waitSignal(page_view.zoom_changed, timeout=1000):
            page_view.set_fit_width()

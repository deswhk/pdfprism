"""Tests for the PageView widget."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsPolygonItem

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.types import SearchHit
from pdfprism.ui.page_cache import PageCache
from pdfprism.ui.widgets.page_view import (
    PageView,
    ToolMode,
    ViewMode,
    ZoomMode,
)


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


class TestHighlights:
    def test_no_highlights_initially(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        rects = [i for i in page_view.scene().items() if isinstance(i, QGraphicsPolygonItem)]
        assert rects == []

    def test_set_search_hits_draws_one_per_match(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        hits = [
            SearchHit(page_index=0, x0=72, y0=100, x1=200, y1=120),
            SearchHit(page_index=0, x0=72, y0=150, x1=200, y1=170),
        ]
        page_view.set_search_hits(hits)
        rects = [i for i in page_view.scene().items() if isinstance(i, QGraphicsPolygonItem)]
        assert len(rects) == 2

    def test_only_current_page_hits_drawn(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        hits = [
            SearchHit(page_index=0, x0=72, y0=100, x1=200, y1=120),
            SearchHit(page_index=1, x0=72, y0=100, x1=200, y1=120),
            SearchHit(page_index=2, x0=72, y0=100, x1=200, y1=120),
        ]
        page_view.set_search_hits(hits)
        assert page_view.current_page == 0
        rects = [i for i in page_view.scene().items() if isinstance(i, QGraphicsPolygonItem)]
        assert len(rects) == 1

    def test_navigation_redraws_for_new_page(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        hits = [
            SearchHit(page_index=0, x0=72, y0=100, x1=200, y1=120),
            SearchHit(page_index=1, x0=72, y0=100, x1=200, y1=120),
            SearchHit(page_index=1, x0=72, y0=150, x1=200, y1=170),
        ]
        page_view.set_search_hits(hits)
        page_view.go_to_page(1)
        rects = [i for i in page_view.scene().items() if isinstance(i, QGraphicsPolygonItem)]
        assert len(rects) == 2

    def test_set_current_hit_navigates(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        hits = [SearchHit(page_index=2, x0=72, y0=100, x1=200, y1=120)]
        page_view.set_search_hits(hits)
        page_view.set_current_hit(hits[0])
        assert page_view.current_page == 2

    def test_current_hit_uses_different_color(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        hits = [
            SearchHit(page_index=0, x0=72, y0=100, x1=200, y1=120),
            SearchHit(page_index=0, x0=72, y0=150, x1=200, y1=170),
        ]
        page_view.set_search_hits(hits)
        page_view.set_current_hit(hits[0])
        rects = sorted(
            [i for i in page_view.scene().items() if isinstance(i, QGraphicsPolygonItem)],
            key=lambda r: r.boundingRect().y(),
        )
        assert len(rects) == 2
        assert rects[0].brush().color() != rects[1].brush().color()

    def test_clear_search_removes_highlights(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        hits = [SearchHit(page_index=0, x0=72, y0=100, x1=200, y1=120)]
        page_view.set_search_hits(hits)
        page_view.clear_search()
        rects = [i for i in page_view.scene().items() if isinstance(i, QGraphicsPolygonItem)]
        assert rects == []

    def test_set_adapter_clears_search(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        hits = [SearchHit(page_index=0, x0=72, y0=100, x1=200, y1=120)]
        page_view.set_search_hits(hits)
        page_view.set_adapter(adapter_with_doc)  # rebind same adapter
        rects = [i for i in page_view.scene().items() if isinstance(i, QGraphicsPolygonItem)]
        assert rects == []


class TestViewMode:
    def test_default_view_mode_is_single_page(self, page_view: PageView) -> None:
        assert page_view.view_mode == ViewMode.SINGLE_PAGE

    def test_single_page_mode_has_one_pixmap(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        items = [i for i in page_view.scene().items() if isinstance(i, QGraphicsPixmapItem)]
        assert len(items) == 1

    def test_continuous_mode_renders_all_pages(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.set_view_mode(ViewMode.CONTINUOUS)
        items = [i for i in page_view.scene().items() if isinstance(i, QGraphicsPixmapItem)]
        assert len(items) == 3

    def test_switching_back_to_single_reduces_items(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.set_view_mode(ViewMode.CONTINUOUS)
        page_view.set_view_mode(ViewMode.SINGLE_PAGE)
        items = [i for i in page_view.scene().items() if isinstance(i, QGraphicsPixmapItem)]
        assert len(items) == 1

    def test_mode_set_before_adapter_is_honored(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_view_mode(ViewMode.CONTINUOUS)
        page_view.set_adapter(adapter_with_doc)
        assert page_view.view_mode == ViewMode.CONTINUOUS
        items = [i for i in page_view.scene().items() if isinstance(i, QGraphicsPixmapItem)]
        assert len(items) == 3

    def test_continuous_highlights_show_across_pages(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.set_view_mode(ViewMode.CONTINUOUS)
        hits = [
            SearchHit(page_index=0, x0=72, y0=100, x1=200, y1=120),
            SearchHit(page_index=1, x0=72, y0=100, x1=200, y1=120),
            SearchHit(page_index=2, x0=72, y0=100, x1=200, y1=120),
        ]
        page_view.set_search_hits(hits)
        rects = [i for i in page_view.scene().items() if isinstance(i, QGraphicsPolygonItem)]
        assert len(rects) == 3

    def test_set_same_mode_is_noop(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.set_view_mode(ViewMode.SINGLE_PAGE)
        page_view.set_view_mode(ViewMode.SINGLE_PAGE)
        assert page_view.view_mode == ViewMode.SINGLE_PAGE

    def test_set_view_mode_emits_signal(self, page_view: PageView, qtbot) -> None:
        with qtbot.waitSignal(page_view.view_mode_changed, timeout=1000) as blocker:
            page_view.set_view_mode(ViewMode.CONTINUOUS)
        assert blocker.args == [ViewMode.CONTINUOUS]


class TestQuadHighlights:
    """When SearchHit.quad is populated (rotated pages), the polygon item
    uses those four corners verbatim rather than synthesizing an
    axis-aligned polygon from x0/y0/x1/y1."""

    def test_quad_corners_used_in_polygon(self, page_view, sample_pdf_path):
        from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
        from pdfprism.core.types import SearchHit

        adapter = PyMuPDFAdapter()
        adapter.open(sample_pdf_path)
        try:
            page_view.set_adapter(adapter)
            page_view.go_to_page(0)
            # Synthetic quad: trapezoid that is clearly non-axis-aligned.
            quad = ((10.0, 20.0), (110.0, 25.0), (105.0, 60.0), (15.0, 55.0))
            hit = SearchHit(
                page_index=0,
                x0=10.0,
                y0=20.0,
                x1=110.0,
                y1=60.0,
                quad=quad,
            )
            page_view.set_search_hits([hit])

            polys = [i for i in page_view.scene().items() if isinstance(i, QGraphicsPolygonItem)]
            assert len(polys) == 1
            qp = polys[0].polygon()
            # Four points, each from the synthetic quad scaled by _RENDER_SCALE.
            from pdfprism.ui.widgets.page_view import _RENDER_SCALE

            expected = [(x * _RENDER_SCALE, y * _RENDER_SCALE) for x, y in quad]
            got = [(qp.at(i).x(), qp.at(i).y()) for i in range(qp.count())]
            assert got == expected
        finally:
            adapter.close()

    def test_no_quad_falls_back_to_axis_aligned(self, page_view, sample_pdf_path):
        """quad=None still works -- axis-aligned polygon from bbox."""
        from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
        from pdfprism.core.types import SearchHit

        adapter = PyMuPDFAdapter()
        adapter.open(sample_pdf_path)
        try:
            page_view.set_adapter(adapter)
            page_view.go_to_page(0)
            hit = SearchHit(
                page_index=0,
                x0=10.0,
                y0=20.0,
                x1=110.0,
                y1=60.0,
                quad=None,
            )
            page_view.set_search_hits([hit])
            polys = [i for i in page_view.scene().items() if isinstance(i, QGraphicsPolygonItem)]
            assert len(polys) == 1
            br = polys[0].boundingRect()
            # Axis-aligned: width/height match the bbox extent
            from pdfprism.ui.widgets.page_view import _RENDER_SCALE

            assert br.width() == 100.0 * _RENDER_SCALE
            assert br.height() == 40.0 * _RENDER_SCALE
        finally:
            adapter.close()


class TestSelection:
    def test_default_tool_mode_is_hand(self, page_view: PageView) -> None:
        assert page_view.tool_mode == ToolMode.HAND

    def test_default_selected_text_is_empty(self, page_view: PageView) -> None:
        assert page_view.selected_text == ""

    def test_set_tool_mode_changes_mode(self, page_view: PageView) -> None:
        page_view.set_tool_mode(ToolMode.SELECT)
        assert page_view.tool_mode == ToolMode.SELECT

    def test_set_tool_mode_emits_signal(self, page_view: PageView, qtbot) -> None:
        with qtbot.waitSignal(page_view.tool_mode_changed, timeout=500) as blocker:
            page_view.set_tool_mode(ToolMode.SELECT)
        assert blocker.args == [ToolMode.SELECT]

    def test_drag_selects_matching_words(
        self,
        page_view: PageView,
        adapter_with_doc: PyMuPDFAdapter,
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.set_tool_mode(ToolMode.SELECT)
        words = adapter_with_doc.extract_words(0)
        hello = next(w for w in words if w.text == "Hello")
        # _RENDER_SCALE is 2.0 -- scene coords are PDF coords * 2.
        render_scale = 2.0
        anchor = QPointF((hello.x0 - 1) * render_scale, (hello.y0 - 1) * render_scale)
        current = QPointF((hello.x1 + 1) * render_scale, (hello.y1 + 1) * render_scale)
        page_view._update_selection_from_drag(anchor, current)
        assert page_view.selected_text == "Hello"

    def test_clear_selection_resets_text(
        self,
        page_view: PageView,
        adapter_with_doc: PyMuPDFAdapter,
    ) -> None:
        page_view.set_adapter(adapter_with_doc)
        page_view.set_tool_mode(ToolMode.SELECT)
        words = adapter_with_doc.extract_words(0)
        hello = next(w for w in words if w.text == "Hello")
        render_scale = 2.0
        page_view._update_selection_from_drag(
            QPointF((hello.x0 - 1) * render_scale, (hello.y0 - 1) * render_scale),
            QPointF((hello.x1 + 1) * render_scale, (hello.y1 + 1) * render_scale),
        )
        assert page_view.selected_text == "Hello"
        page_view.clear_selection()
        assert page_view.selected_text == ""


# ---- PR 12: Redaction mode interaction ---------------------------------


class TestRedactionModeSetup:
    """Tool-mode transitions to REDACTION."""

    def test_redaction_mode_sets_cross_cursor(self, page_view: PageView) -> None:
        """Positive: REDACTION mode uses cross cursor."""
        from PySide6.QtCore import Qt

        page_view.set_tool_mode(ToolMode.REDACTION)
        assert page_view.viewport().cursor().shape() == Qt.CursorShape.CrossCursor

    def test_redaction_mode_clears_text_selection(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        """Positive: switching to REDACTION clears any prior text selection."""
        page_view.set_adapter(adapter_with_doc)
        # Simulate having some selected words
        from pdfprism.core.types import Word

        page_view._selected_words = [
            Word(text="stub", x0=0.0, y0=0.0, x1=10.0, y1=10.0),
        ]
        page_view.set_tool_mode(ToolMode.REDACTION)
        assert page_view._selected_words == []


class TestRedactionDrag:
    """Mouse drag interaction: emits redaction_requested with page-space coords."""

    def test_press_captures_anchor(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter, qtbot
    ) -> None:
        """Positive: mouse press in REDACTION mode captures anchor position."""
        from PySide6.QtCore import QPoint, Qt

        page_view.set_adapter(adapter_with_doc)
        page_view.set_tool_mode(ToolMode.REDACTION)
        qtbot.mousePress(page_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        assert page_view._redaction_anchor is not None

    def test_move_creates_temp_overlay(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter, qtbot
    ) -> None:
        """Positive: mouse move after press adds a temp overlay QGraphicsRectItem."""
        from PySide6.QtCore import QPoint, Qt

        page_view.set_adapter(adapter_with_doc)
        page_view.set_tool_mode(ToolMode.REDACTION)
        qtbot.mousePress(page_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        assert page_view._redaction_temp_item is None
        qtbot.mouseMove(page_view.viewport(), pos=QPoint(200, 150))
        assert page_view._redaction_temp_item is not None

    def test_release_emits_signal_with_page_space_coords(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter, qtbot
    ) -> None:
        """Positive: valid drag release emits redaction_requested with (page_index, rect)."""
        from PySide6.QtCore import QPoint, Qt

        page_view.set_adapter(adapter_with_doc)
        page_view.set_tool_mode(ToolMode.REDACTION)

        emitted: list = []
        page_view.redaction_requested.connect(lambda p, r: emitted.append((p, r)))

        qtbot.mousePress(page_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        qtbot.mouseMove(page_view.viewport(), pos=QPoint(200, 150))
        qtbot.mouseRelease(page_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(200, 150))

        assert len(emitted) == 1
        page_index, rect = emitted[0]
        assert page_index == 0
        # Rect should be a 4-tuple in ascending x, y order
        x0, y0, x1, y1 = rect
        assert x0 <= x1 and y0 <= y1

    def test_tiny_drag_does_not_emit(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter, qtbot
    ) -> None:
        """Positive: drags smaller than 5x5 scene px are ignored (accidental click)."""
        from PySide6.QtCore import QPoint, Qt

        page_view.set_adapter(adapter_with_doc)
        page_view.set_tool_mode(ToolMode.REDACTION)

        emitted: list = []
        page_view.redaction_requested.connect(lambda p, r: emitted.append((p, r)))

        # Press + release with no meaningful move -- below threshold.
        # (The threshold is 5 scene pixels; a stray click can register a
        # tiny drag due to rounding, so we assert nothing was emitted for
        # a same-position release.)
        qtbot.mousePress(page_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        qtbot.mouseRelease(page_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(100, 100))

        assert emitted == []

    def test_release_clears_temp_overlay(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter, qtbot
    ) -> None:
        """Positive: after release, temp overlay item is removed from scene."""
        from PySide6.QtCore import QPoint, Qt

        page_view.set_adapter(adapter_with_doc)
        page_view.set_tool_mode(ToolMode.REDACTION)

        qtbot.mousePress(page_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        qtbot.mouseMove(page_view.viewport(), pos=QPoint(200, 150))
        assert page_view._redaction_temp_item is not None
        qtbot.mouseRelease(page_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(200, 150))
        assert page_view._redaction_temp_item is None
        assert page_view._redaction_anchor is None


class TestRedactionEscapeCancel:
    """Escape mid-drag cancels the pending redaction."""

    def test_escape_mid_drag_cancels(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter, qtbot
    ) -> None:
        """Positive: Escape during a drag removes temp overlay + clears anchor."""
        from PySide6.QtCore import QPoint, Qt

        page_view.set_adapter(adapter_with_doc)
        page_view.set_tool_mode(ToolMode.REDACTION)

        emitted: list = []
        page_view.redaction_requested.connect(lambda p, r: emitted.append((p, r)))

        qtbot.mousePress(page_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        qtbot.mouseMove(page_view.viewport(), pos=QPoint(200, 150))
        assert page_view._redaction_temp_item is not None
        qtbot.keyPress(page_view, Qt.Key.Key_Escape)
        assert page_view._redaction_temp_item is None
        assert page_view._redaction_anchor is None
        assert emitted == []

    def test_escape_without_drag_is_noop(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter, qtbot
    ) -> None:
        """Positive: Escape when no drag in progress doesn't error."""
        from PySide6.QtCore import Qt

        page_view.set_adapter(adapter_with_doc)
        page_view.set_tool_mode(ToolMode.REDACTION)
        # No drag started. Escape should just pass through cleanly.
        qtbot.keyPress(page_view, Qt.Key.Key_Escape)


class TestRedactionModeIsolation:
    """Other tool modes don't produce redaction signals."""

    def test_hand_mode_no_redaction(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter, qtbot
    ) -> None:
        """Positive: drag in HAND mode doesn't emit redaction_requested."""
        from PySide6.QtCore import QPoint, Qt

        page_view.set_adapter(adapter_with_doc)
        page_view.set_tool_mode(ToolMode.HAND)

        emitted: list = []
        page_view.redaction_requested.connect(lambda p, r: emitted.append((p, r)))

        qtbot.mousePress(page_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        qtbot.mouseMove(page_view.viewport(), pos=QPoint(200, 150))
        qtbot.mouseRelease(page_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(200, 150))

        assert emitted == []

    def test_select_mode_no_redaction(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter, qtbot
    ) -> None:
        """Positive: drag in SELECT mode doesn't emit redaction_requested."""
        from PySide6.QtCore import QPoint, Qt

        page_view.set_adapter(adapter_with_doc)
        page_view.set_tool_mode(ToolMode.SELECT)

        emitted: list = []
        page_view.redaction_requested.connect(lambda p, r: emitted.append((p, r)))

        qtbot.mousePress(page_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        qtbot.mouseMove(page_view.viewport(), pos=QPoint(200, 150))
        qtbot.mouseRelease(page_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(200, 150))

        assert emitted == []


# ---- PR 12.1: text-selection redaction (slot-focused) ---------------------


class TestRedactSelectionSlot:
    """PR 12.1: _on_redact_selection slot and its signal emission."""

    def test_slot_emits_signal_with_current_selection(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        """Positive: slot emits (current_page, list-of-selected-Words)."""
        from pdfprism.core.types import Word

        page_view.set_adapter(adapter_with_doc)
        words = [
            Word(text="A", x0=0.0, y0=0.0, x1=10.0, y1=10.0),
            Word(text="B", x0=15.0, y0=0.0, x1=25.0, y1=10.0),
        ]
        page_view._selected_words = list(words)
        page_view._current_page = 0

        emitted: list = []
        page_view.redact_selection_requested.connect(lambda p, w: emitted.append((p, w)))
        page_view._on_redact_selection()

        assert len(emitted) == 1
        got_page, got_words = emitted[0]
        assert got_page == 0
        assert got_words == words

    def test_slot_noop_without_selection(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        """Positive: slot does not emit when no words are selected."""
        page_view.set_adapter(adapter_with_doc)
        page_view._selected_words = []

        emitted: list = []
        page_view.redact_selection_requested.connect(lambda p, w: emitted.append((p, w)))
        page_view._on_redact_selection()
        assert emitted == []

    def test_slot_emits_copy_of_selection(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        """Positive: emitted list is decoupled from internal state.

        Slot emits list(self._selected_words), so if selection is
        cleared afterwards the receiver still holds the words.
        """
        from pdfprism.core.types import Word

        page_view.set_adapter(adapter_with_doc)
        page_view._selected_words = [
            Word(text="A", x0=0.0, y0=0.0, x1=10.0, y1=10.0),
        ]
        page_view._current_page = 0

        received_words: list = []
        page_view.redact_selection_requested.connect(lambda p, w: received_words.extend(w))
        page_view._on_redact_selection()

        # After emit, clear internal selection
        page_view._selected_words = []
        # Received words should still have the original entries
        assert len(received_words) == 1
        assert received_words[0].text == "A"

    def test_signal_exists(self, page_view: PageView) -> None:
        """Positive: redact_selection_requested signal is defined on class."""
        assert hasattr(page_view, "redact_selection_requested")


# ---- PR 12.5: right-click Remove This Mark ------------------------------


class TestHitTestRedaction:
    """PR 12.5: _hit_test_redaction returns (page_index, index) or None."""

    def test_point_inside_mark_returns_hit(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        """Positive: scene point inside a pending mark returns (page, index)."""
        from PySide6.QtCore import QPointF

        from pdfprism.core.types import Redaction

        page_view.set_adapter(adapter_with_doc)
        page_view._current_page = 0

        # Add a redaction in page space; scene = page * _RENDER_SCALE
        adapter_with_doc.add_redaction(Redaction(page_index=0, rect=(50.0, 50.0, 100.0, 80.0)))
        # Scene coords: use midpoint of the rect * 2 (scale)
        from pdfprism.ui.widgets.page_view import _RENDER_SCALE

        scene = QPointF(75.0 * _RENDER_SCALE, 65.0 * _RENDER_SCALE)
        got = page_view._hit_test_redaction(scene)
        assert got == (0, 0)

    def test_point_outside_marks_returns_none(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        """Positive: scene point not inside any mark returns None."""
        from PySide6.QtCore import QPointF

        from pdfprism.core.types import Redaction

        page_view.set_adapter(adapter_with_doc)
        page_view._current_page = 0

        adapter_with_doc.add_redaction(Redaction(page_index=0, rect=(50.0, 50.0, 100.0, 80.0)))
        # Far outside
        got = page_view._hit_test_redaction(QPointF(1000.0, 1000.0))
        assert got is None

    def test_overlapping_marks_returns_last_added(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        """Positive: two marks overlap -> the last-added one wins."""
        from PySide6.QtCore import QPointF

        from pdfprism.core.types import Redaction

        page_view.set_adapter(adapter_with_doc)
        page_view._current_page = 0

        # Two overlapping marks
        adapter_with_doc.add_redaction(Redaction(page_index=0, rect=(0.0, 0.0, 100.0, 100.0)))
        adapter_with_doc.add_redaction(Redaction(page_index=0, rect=(50.0, 50.0, 150.0, 150.0)))

        from pdfprism.ui.widgets.page_view import _RENDER_SCALE

        # Point (75, 75) hits both -> should return index 1 (last added)
        scene = QPointF(75.0 * _RENDER_SCALE, 75.0 * _RENDER_SCALE)
        got = page_view._hit_test_redaction(scene)
        assert got == (0, 1)

    def test_no_adapter_returns_none(self, page_view: PageView) -> None:
        """Positive: no adapter bound -> None (defensive)."""
        from PySide6.QtCore import QPointF

        got = page_view._hit_test_redaction(QPointF(50.0, 50.0))
        assert got is None


class TestRemoveMarkSignal:
    """PR 12.5: remove_mark_requested signal is emitted with correct args."""

    def test_signal_exists(self, page_view: PageView) -> None:
        """Positive: signal is defined on class."""
        assert hasattr(page_view, "remove_mark_requested")

    def test_signal_emits_correct_args(
        self, page_view: PageView, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        """Positive: emit fires with (page_index, redaction_index)."""
        page_view.set_adapter(adapter_with_doc)
        received: list = []
        page_view.remove_mark_requested.connect(lambda p, i: received.append((p, i)))
        page_view.remove_mark_requested.emit(0, 3)
        assert received == [(0, 3)]

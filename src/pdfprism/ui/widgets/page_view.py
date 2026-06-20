"""PageView widget: single-page PDF view with zoom, navigation, search highlights."""

from enum import StrEnum

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPen,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)

from pdfprism.core.document import DocumentAdapter
from pdfprism.core.types import SearchHit
from pdfprism.ui.page_cache import PageCache


class ZoomMode(StrEnum):
    """How the displayed zoom is determined."""

    FIT_PAGE = "fit_page"
    FIT_WIDTH = "fit_width"
    ACTUAL_SIZE = "actual_size"
    CUSTOM = "custom"


# Oversample factor passed to the cache when rendering. Higher values give
# better quality at zoom > 100% at the cost of memory and render time.
_RENDER_SCALE = 2.0

# Min / max custom zoom (Acrobat-style; 1.0 = 100%).
_MIN_ZOOM = 0.1
_MAX_ZOOM = 10.0

# Step multipliers for zoom_in / zoom_out.
_ZOOM_STEP_IN = 1.25
_ZOOM_STEP_OUT = 0.8

# Search-highlight colors. Semi-transparent so the underlying text stays
# readable. Yellow for "all other matches on this page", orange for "the
# one you're currently navigated to".
_HIGHLIGHT_OTHER = QColor(255, 235, 59, 110)
_HIGHLIGHT_CURRENT = QColor(255, 152, 0, 160)


class PageView(QGraphicsView):
    """Zoomable, pannable view of one PDF page at a time.

    Renders through a shared ``PageCache``. Search highlights are drawn as
    overlay rect items on the scene (not baked into the cached pixmap),
    so they can be added, removed, and recolored without invalidating
    the cache.

    Signals:
        page_changed(int): emitted when the displayed page index changes
            (0-based).
        zoom_changed(float): emitted when the effective zoom changes
            (1.0 = 100%, Acrobat-style).
    """

    page_changed = Signal(int)
    zoom_changed = Signal(float)

    def __init__(
        self,
        page_cache: PageCache,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None

        self._page_cache = page_cache
        self._page_count: int = 0
        self._current_page: int = 0
        self._zoom_mode: ZoomMode = ZoomMode.FIT_PAGE
        self._custom_zoom: float = 1.0

        self._search_hits: list[SearchHit] = []
        self._current_hit: SearchHit | None = None
        self._highlight_items: list[QGraphicsRectItem] = []

        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)

    # ----- document binding -----

    def set_adapter(self, adapter: DocumentAdapter | None) -> None:
        """Bind to a document via the shared cache and render page 1.

        The cache's existing entries are cleared because they belonged to a
        previous document. Search state is also cleared. Pass ``None`` to
        unbind.
        """
        self._page_cache.set_adapter(adapter)
        self._page_count = adapter.page_count if adapter is not None else 0
        self._current_page = 0
        self._search_hits = []
        self._current_hit = None
        if self._page_count > 0:
            self._render_current_page()
            self.page_changed.emit(self._current_page)

    def clear(self) -> None:
        """Clear the view's local state. Leaves the shared cache alone."""
        self._scene.clear()
        self._pixmap_item = None
        self._highlight_items = []
        self._page_count = 0
        self._current_page = 0
        self._search_hits = []
        self._current_hit = None

    # ----- read-only state -----

    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def current_page(self) -> int:
        return self._current_page

    @property
    def zoom_mode(self) -> ZoomMode:
        return self._zoom_mode

    @property
    def effective_zoom(self) -> float:
        """Current effective zoom in Acrobat terms (1.0 = 100% = actual size)."""
        return self.transform().m11() * _RENDER_SCALE

    # ----- navigation -----

    def go_to_page(self, index: int) -> None:
        """Jump to page ``index`` (0-based). No-op if out of range or unchanged."""
        if self._page_count == 0:
            return
        if not (0 <= index < self._page_count):
            return
        if index == self._current_page:
            return
        self._current_page = index
        self._render_current_page()
        self.page_changed.emit(self._current_page)

    def next_page(self) -> None:
        if self._page_count == 0:
            return
        self.go_to_page(self._current_page + 1)

    def prev_page(self) -> None:
        if self._page_count == 0:
            return
        self.go_to_page(self._current_page - 1)

    def first_page(self) -> None:
        self.go_to_page(0)

    def last_page(self) -> None:
        if self._page_count == 0:
            return
        self.go_to_page(self._page_count - 1)

    # ----- zoom -----

    def set_fit_page(self) -> None:
        self._zoom_mode = ZoomMode.FIT_PAGE
        self._apply_zoom_mode()

    def set_fit_width(self) -> None:
        self._zoom_mode = ZoomMode.FIT_WIDTH
        self._apply_zoom_mode()

    def set_actual_size(self) -> None:
        self._zoom_mode = ZoomMode.ACTUAL_SIZE
        self._custom_zoom = 1.0
        self._apply_zoom_mode()

    def set_custom_zoom(self, ratio: float) -> None:
        """Set a custom zoom level (1.0 = 100%)."""
        self._custom_zoom = max(_MIN_ZOOM, min(ratio, _MAX_ZOOM))
        self._zoom_mode = ZoomMode.CUSTOM
        self._apply_zoom_mode()

    def zoom_in(self) -> None:
        self.set_custom_zoom(self.effective_zoom * _ZOOM_STEP_IN)

    def zoom_out(self) -> None:
        self.set_custom_zoom(self.effective_zoom * _ZOOM_STEP_OUT)

    # ----- search highlights -----

    def set_search_hits(self, hits: list[SearchHit]) -> None:
        """Stash all search hits and redraw highlights for the current page.

        Hits on other pages are kept in state and re-appear when the user
        navigates to those pages.
        """
        self._search_hits = list(hits)
        self._refresh_highlights()

    def set_current_hit(self, hit: SearchHit | None) -> None:
        """Mark ``hit`` as the active match (orange) and navigate to its page.

        If ``hit`` lives on a different page than the one currently shown,
        the view navigates to that page first; the highlight refresh runs
        as part of rendering.
        """
        self._current_hit = hit
        if hit is not None and hit.page_index != self._current_page:
            self.go_to_page(hit.page_index)
        else:
            self._refresh_highlights()

    def clear_search(self) -> None:
        """Remove all search state and highlights."""
        self._search_hits = []
        self._current_hit = None
        self._clear_highlight_items()

    # ----- rendering -----

    def _render_current_page(self) -> None:
        if self._page_count == 0:
            return
        pixmap = self._page_cache.get_or_render(self._current_page, zoom=_RENDER_SCALE)
        self._scene.clear()
        self._highlight_items = []
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self._apply_zoom_mode()
        self._refresh_highlights()

    def _refresh_highlights(self) -> None:
        self._clear_highlight_items()
        if self._pixmap_item is None:
            return
        for hit in self._search_hits:
            if hit.page_index != self._current_page:
                continue
            color = _HIGHLIGHT_CURRENT if hit == self._current_hit else _HIGHLIGHT_OTHER
            self._add_highlight_rect(hit, color)

    def _add_highlight_rect(self, hit: SearchHit, color: QColor) -> None:
        item = QGraphicsRectItem(
            hit.x0 * _RENDER_SCALE,
            hit.y0 * _RENDER_SCALE,
            (hit.x1 - hit.x0) * _RENDER_SCALE,
            (hit.y1 - hit.y0) * _RENDER_SCALE,
        )
        item.setBrush(QBrush(color))
        item.setPen(QPen(Qt.PenStyle.NoPen))
        item.setZValue(1.0)
        self._scene.addItem(item)
        self._highlight_items.append(item)

    def _clear_highlight_items(self) -> None:
        for item in self._highlight_items:
            self._scene.removeItem(item)
        self._highlight_items = []

    def _apply_zoom_mode(self) -> None:
        if self._pixmap_item is None:
            return
        if self._zoom_mode == ZoomMode.FIT_PAGE:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        elif self._zoom_mode == ZoomMode.FIT_WIDTH:
            view_w = self.viewport().width()
            item_w = self._pixmap_item.boundingRect().width()
            self.resetTransform()
            if item_w > 0:
                ratio = view_w / item_w
                self.scale(ratio, ratio)
        elif self._zoom_mode == ZoomMode.ACTUAL_SIZE:
            self.resetTransform()
            self.scale(1.0 / _RENDER_SCALE, 1.0 / _RENDER_SCALE)
        elif self._zoom_mode == ZoomMode.CUSTOM:
            self.resetTransform()
            s = self._custom_zoom / _RENDER_SCALE
            self.scale(s, s)
        self.zoom_changed.emit(self.effective_zoom)

    # ----- events -----

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._zoom_mode in (ZoomMode.FIT_PAGE, ZoomMode.FIT_WIDTH):
            self._apply_zoom_mode()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

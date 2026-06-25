"""PageView widget: PDF view with zoom, navigation, view modes, search highlights."""

from enum import StrEnum

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPen,
    QPolygonF,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
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


class ViewMode(StrEnum):
    """How pages are laid out in the view."""

    SINGLE_PAGE = "single_page"
    CONTINUOUS = "continuous"


_RENDER_SCALE = 2.0
_MIN_ZOOM = 0.1
_MAX_ZOOM = 10.0
_ZOOM_STEP_IN = 1.25
_ZOOM_STEP_OUT = 0.8

# Vertical spacing between pages in continuous mode (in scene units == pixmap px).
_PAGE_SPACING = 24.0

_HIGHLIGHT_OTHER = QColor(255, 235, 59, 110)
_HIGHLIGHT_CURRENT = QColor(255, 152, 0, 160)


class PageView(QGraphicsView):
    """Zoomable, pannable PDF view supporting single-page and continuous modes.

    The scene contains one or more page pixmap items, positioned according
    to the active view mode. In single-page mode the scene has exactly one
    item (the current page). In continuous mode all pages are present,
    stacked vertically with ``_PAGE_SPACING`` between them.

    Current page semantics by mode:
        - Single page: the page actually rendered to the scene.
        - Continuous: the page whose top crosses the viewport top, derived
          from scroll position via ``_on_scroll``.

    Search highlights are scene overlays. Single-page shows only the current
    page's hits; continuous shows all hits, each translated to its page's
    scene offset.

    Signals:
        page_changed(int): current page index changed (0-based).
        zoom_changed(float): effective zoom changed (1.0 = 100%, Acrobat).
    """

    page_changed = Signal(int)
    zoom_changed = Signal(float)
    view_mode_changed = Signal(ViewMode)

    def __init__(
        self,
        page_cache: PageCache,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_items: list[QGraphicsPixmapItem] = []
        self._page_offsets: list[float] = []

        self._page_cache = page_cache
        self._page_count: int = 0
        self._current_page: int = 0
        self._view_mode: ViewMode = ViewMode.SINGLE_PAGE
        self._zoom_mode: ZoomMode = ZoomMode.FIT_PAGE
        self._custom_zoom: float = 1.0
        self._building_layout: bool = False

        self._search_hits: list[SearchHit] = []
        self._current_hit: SearchHit | None = None
        self._highlight_items: list[QGraphicsPolygonItem] = []

        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    # ----- document binding -----

    def set_adapter(self, adapter: DocumentAdapter | None) -> None:
        self._page_cache.set_adapter(adapter)
        self._page_count = adapter.page_count if adapter is not None else 0
        self._current_page = 0
        self._search_hits = []
        self._current_hit = None
        if self._page_count > 0:
            self._build_layout()
            self.page_changed.emit(self._current_page)

    def clear(self) -> None:
        self._scene.clear()
        self._pixmap_items = []
        self._page_offsets = []
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
    def view_mode(self) -> ViewMode:
        return self._view_mode

    @property
    def zoom_mode(self) -> ZoomMode:
        return self._zoom_mode

    @property
    def effective_zoom(self) -> float:
        return self.transform().m11() * _RENDER_SCALE

    # ----- view mode -----

    def set_view_mode(self, mode: ViewMode) -> None:
        """Switch view mode, preserving current page and search state."""
        if mode == self._view_mode:
            return
        self._view_mode = mode
        if self._page_count > 0:
            self._build_layout()
            self._scroll_to_current_page()
        self.view_mode_changed.emit(mode)

    # ----- navigation -----

    def go_to_page(self, index: int) -> None:
        if self._page_count == 0:
            return
        if not (0 <= index < self._page_count):
            return
        if index == self._current_page:
            return
        self._current_page = index
        if self._view_mode == ViewMode.SINGLE_PAGE:
            self._build_layout()
        else:
            self._scroll_to_current_page()
            self._refresh_highlights()
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
        self._custom_zoom = max(_MIN_ZOOM, min(ratio, _MAX_ZOOM))
        self._zoom_mode = ZoomMode.CUSTOM
        self._apply_zoom_mode()

    def zoom_in(self) -> None:
        self.set_custom_zoom(self.effective_zoom * _ZOOM_STEP_IN)

    def zoom_out(self) -> None:
        self.set_custom_zoom(self.effective_zoom * _ZOOM_STEP_OUT)

    # ----- search highlights -----

    def set_search_hits(self, hits: list[SearchHit]) -> None:
        self._search_hits = list(hits)
        self._refresh_highlights()

    def set_current_hit(self, hit: SearchHit | None) -> None:
        self._current_hit = hit
        if hit is not None and hit.page_index != self._current_page:
            self.go_to_page(hit.page_index)
        else:
            self._refresh_highlights()
        if hit is not None:
            self._ensure_hit_visible(hit)

    def clear_search(self) -> None:
        self._search_hits = []
        self._current_hit = None
        self._clear_highlight_items()

    def _ensure_hit_visible(self, hit: SearchHit) -> None:
        """Scroll the view so the given hit's rect is in the viewport."""
        if not self._pixmap_items:
            return
        if self._view_mode == ViewMode.CONTINUOUS:
            if not (0 <= hit.page_index < len(self._page_offsets)):
                return
            y_offset = self._page_offsets[hit.page_index]
        else:
            if hit.page_index != self._current_page:
                return
            y_offset = 0.0
        rect = QRectF(
            hit.x0 * _RENDER_SCALE,
            hit.y0 * _RENDER_SCALE + y_offset,
            (hit.x1 - hit.x0) * _RENDER_SCALE,
            (hit.y1 - hit.y0) * _RENDER_SCALE,
        )
        self.ensureVisible(rect, 50, 50)

    # ----- layout (private) -----

    def _build_layout(self) -> None:
        """Rebuild the scene according to the current view mode."""
        self._building_layout = True
        try:
            self._scene.clear()
            self._pixmap_items = []
            self._page_offsets = []
            self._highlight_items = []

            if self._page_count == 0:
                return

            if self._view_mode == ViewMode.SINGLE_PAGE:
                self._build_single_page_layout()
            else:
                self._build_continuous_layout()

            self._apply_zoom_mode()
            self._refresh_highlights()
        finally:
            self._building_layout = False

    def _build_single_page_layout(self) -> None:
        pixmap = self._page_cache.get_or_render(self._current_page, zoom=_RENDER_SCALE)
        item = self._scene.addPixmap(pixmap)
        item.setPos(0, 0)
        self._pixmap_items.append(item)
        self._page_offsets.append(0.0)
        self._scene.setSceneRect(item.boundingRect())

    def _build_continuous_layout(self) -> None:
        y = 0.0
        max_w = 0.0
        for i in range(self._page_count):
            pixmap = self._page_cache.get_or_render(i, zoom=_RENDER_SCALE)
            item = self._scene.addPixmap(pixmap)
            item.setPos(0, y)
            self._pixmap_items.append(item)
            self._page_offsets.append(y)
            y += float(pixmap.height()) + _PAGE_SPACING
            max_w = max(max_w, float(pixmap.width()))
        self._scene.setSceneRect(0, 0, max_w, y)

    def _scroll_to_current_page(self) -> None:
        if self._view_mode != ViewMode.CONTINUOUS:
            return
        if not (0 <= self._current_page < len(self._page_offsets)):
            return
        y_scene = self._page_offsets[self._current_page]
        target = int(y_scene * self.transform().m22())
        self.verticalScrollBar().setValue(target)

    def _on_scroll(self, _value: int) -> None:
        if self._building_layout:
            return
        if self._view_mode != ViewMode.CONTINUOUS:
            return
        if not self._page_offsets:
            return
        view_top = self.mapToScene(0, 0).y()
        new_current = 0
        for i, offset in enumerate(self._page_offsets):
            if offset > view_top + 1.0:
                break
            new_current = i
        if new_current != self._current_page:
            self._current_page = new_current
            self.page_changed.emit(new_current)

    def _refresh_highlights(self) -> None:
        self._clear_highlight_items()
        if not self._pixmap_items:
            return
        for hit in self._search_hits:
            if self._view_mode == ViewMode.SINGLE_PAGE:
                if hit.page_index != self._current_page:
                    continue
                y_offset = 0.0
            else:
                if not (0 <= hit.page_index < len(self._page_offsets)):
                    continue
                y_offset = self._page_offsets[hit.page_index]
            color = _HIGHLIGHT_CURRENT if hit == self._current_hit else _HIGHLIGHT_OTHER
            self._add_highlight_polygon(hit, color, y_offset)

    def _add_highlight_polygon(self, hit: SearchHit, color: QColor, y_offset: float) -> None:
        # Build a 4-point polygon in scene coordinates. When the adapter
        # populated hit.quad (rotated page), use the four corners directly
        # so the overlay tracks text orientation. Otherwise build an
        # axis-aligned polygon from the bounding rect -- visually identical
        # to the legacy QGraphicsRectItem path but going through the same
        # polygon code path so there is only one renderer to maintain.
        if hit.quad is not None:
            corners = hit.quad
        else:
            corners = (
                (hit.x0, hit.y0),
                (hit.x1, hit.y0),
                (hit.x1, hit.y1),
                (hit.x0, hit.y1),
            )
        polygon = QPolygonF(
            [QPointF(x * _RENDER_SCALE, y * _RENDER_SCALE + y_offset) for x, y in corners]
        )
        item = QGraphicsPolygonItem(polygon)
        item.setBrush(QBrush(color))
        item.setPen(QPen(Qt.PenStyle.NoPen))
        item.setZValue(1.0)
        self._scene.addItem(item)
        self._highlight_items.append(item)

    def _clear_highlight_items(self) -> None:
        for item in self._highlight_items:
            self._scene.removeItem(item)
        self._highlight_items = []

    def _current_pixmap_item(self) -> QGraphicsPixmapItem | None:
        if not self._pixmap_items:
            return None
        if self._view_mode == ViewMode.SINGLE_PAGE:
            return self._pixmap_items[0]
        if 0 <= self._current_page < len(self._pixmap_items):
            return self._pixmap_items[self._current_page]
        return self._pixmap_items[0]

    def _apply_zoom_mode(self) -> None:
        item = self._current_pixmap_item()
        if item is None:
            return
        if self._zoom_mode == ZoomMode.FIT_PAGE:
            self.fitInView(item, Qt.AspectRatioMode.KeepAspectRatio)
        elif self._zoom_mode == ZoomMode.FIT_WIDTH:
            view_w = self.viewport().width()
            item_w = item.boundingRect().width()
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

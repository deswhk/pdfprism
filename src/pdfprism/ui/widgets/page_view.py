"""PageView widget: single-page PDF view with zoom and navigation."""

from enum import StrEnum
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPixmap, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

if TYPE_CHECKING:
    from pdfprism.core.document import DocumentAdapter


class ZoomMode(StrEnum):
    """How the displayed zoom is determined."""

    FIT_PAGE = "fit_page"
    FIT_WIDTH = "fit_width"
    ACTUAL_SIZE = "actual_size"
    CUSTOM = "custom"


# Oversample factor passed to the adapter when rendering. Higher values
# give better quality at zoom > 100% at the cost of memory and render time.
_RENDER_SCALE = 2.0

# Min / max custom zoom (Acrobat-style; 1.0 = 100%).
_MIN_ZOOM = 0.1
_MAX_ZOOM = 10.0

# Step multipliers for zoom_in / zoom_out.
_ZOOM_STEP_IN = 1.25
_ZOOM_STEP_OUT = 0.8


class PageView(QGraphicsView):
    """Zoomable, pannable view of one PDF page at a time.

    Holds a ``DocumentAdapter`` plus view state (current page index, zoom
    mode, custom zoom ratio) and renders on demand. No caching in PR 2;
    the LRU cache for adjacent pages lands in PR 3 alongside thumbnails.

    Signals:
        page_changed(int): emitted when the displayed page index changes
            (0-based).
        zoom_changed(float): emitted when the effective zoom changes
            (1.0 = 100%, Acrobat-style).
    """

    page_changed = Signal(int)
    zoom_changed = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None

        self._adapter: DocumentAdapter | None = None
        self._current_page: int = 0
        self._zoom_mode: ZoomMode = ZoomMode.FIT_PAGE
        self._custom_zoom: float = 1.0

        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)

    # ----- document binding -----

    def set_adapter(self, adapter: "DocumentAdapter") -> None:
        """Bind to an open document and render its first page."""
        self._adapter = adapter
        self._current_page = 0
        self._render_current_page()
        self.page_changed.emit(self._current_page)

    def clear(self) -> None:
        """Clear the view; no document is bound after this."""
        self._scene.clear()
        self._pixmap_item = None
        self._adapter = None
        self._current_page = 0

    # ----- read-only state -----

    @property
    def page_count(self) -> int:
        return self._adapter.page_count if self._adapter else 0

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
        if self._adapter is None:
            return
        if not (0 <= index < self._adapter.page_count):
            return
        if index == self._current_page:
            return
        self._current_page = index
        self._render_current_page()
        self.page_changed.emit(self._current_page)

    def next_page(self) -> None:
        if self._adapter is None:
            return
        self.go_to_page(self._current_page + 1)

    def prev_page(self) -> None:
        if self._adapter is None:
            return
        self.go_to_page(self._current_page - 1)

    def first_page(self) -> None:
        self.go_to_page(0)

    def last_page(self) -> None:
        if self._adapter is None:
            return
        self.go_to_page(self._adapter.page_count - 1)

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

    # ----- rendering -----

    def _render_current_page(self) -> None:
        if self._adapter is None:
            return
        png_bytes = self._adapter.render_page(self._current_page, zoom=_RENDER_SCALE)
        pixmap = QPixmap()
        pixmap.loadFromData(png_bytes, "PNG")
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self._apply_zoom_mode()

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

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
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QMenu,
    QWidget,
)

from pdfprism.core.document import DocumentAdapter
from pdfprism.core.types import SearchHit, Word
from pdfprism.services.extract import _join_words_as_lines
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


class ToolMode(StrEnum):
    """Active mouse-drag tool. HAND pans the view (default); SELECT
    drag-selects text via word-rect hit-testing."""

    HAND = "hand"
    SELECT = "select"
    REDACTION = "redaction"


_RENDER_SCALE = 2.0
_MIN_ZOOM = 0.1
_MAX_ZOOM = 10.0
_ZOOM_STEP_IN = 1.25
_ZOOM_STEP_OUT = 0.8

# Vertical spacing between pages in continuous mode (in scene units == pixmap px).
_PAGE_SPACING = 24.0

_HIGHLIGHT_OTHER = QColor(255, 235, 59, 110)
_HIGHLIGHT_CURRENT = QColor(255, 152, 0, 160)
_HIGHLIGHT_SELECTION = QColor(33, 150, 243, 110)
# PR 12: semi-transparent red overlay for pending redaction drag.
_REDACTION_PENDING = QColor(220, 30, 30, 140)


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
    tool_mode_changed = Signal(ToolMode)
    selection_changed = Signal(str)
    copy_requested = Signal()
    extract_selection_requested = Signal()
    # PR 12: emitted on redaction drag release with (page_index, rect)
    # where rect is (x0, y0, x1, y1) in PDF-space points.
    redaction_requested = Signal(int, tuple)
    # PR 12.1: emitted on "Redact Selection" context menu click.
    # Payload: (page_index, list of Word objects).
    redact_selection_requested = Signal(int, list)
    # PR 12.5: emitted on "Remove This Mark" context menu click.
    # Payload: (page_index, redaction_index_on_that_page).
    remove_mark_requested = Signal(int, int)
    # PR 14b: emitted on "Edit This Group" context menu click.
    # Payload: (page_index, redaction_index_on_that_page).
    # DocumentView slot resolves the mark's group and opens Edit dialog.
    edit_group_requested = Signal(int, int)

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
        self._tool_mode: ToolMode = ToolMode.HAND
        self._selected_words: list[Word] = []
        self._selection_items: list[QGraphicsPolygonItem] = []
        self._selection_anchor: QPointF | None = None
        # PR 12: pending-redaction drag state
        self._redaction_anchor: QPointF | None = None
        self._redaction_temp_item: QGraphicsRectItem | None = None

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

    def _page_at_scene_y(self, y: float) -> int:
        """PR 17.6: return the page_index whose vertical range contains ``y``.

        Uses ``_page_offsets`` (scene-y of each page's top) to find the
        page. If ``y`` is above page 0 or below the last page, clamps
        to the nearest page. Returns -1 only if there are no pages
        (``_page_offsets`` is empty).
        """
        if not self._page_offsets:
            return -1
        # Walk offsets to find the last one whose top is <= y.
        # Same shape as _on_scroll but returns the page instead of updating state.
        found = 0
        for i, offset in enumerate(self._page_offsets):
            if offset > y:
                break
            found = i
        return found

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

    # ----- tool mode + selection -----

    @property
    def tool_mode(self) -> ToolMode:
        return self._tool_mode

    @property
    def selected_text(self) -> str:
        """Selected text in reading order; empty string if no selection."""
        return _join_words_as_lines(self._selected_words)

    def set_tool_mode(self, mode: ToolMode) -> None:
        if mode == self._tool_mode:
            return
        self._tool_mode = mode
        if mode == ToolMode.HAND:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        elif mode == ToolMode.REDACTION:
            # PR 12: our own drag handler (sub-step 6) draws
            # redaction rectangles; disable Qt's built-in drag
            # behaviors so nothing else intercepts the mouse.
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        self.clear_selection()
        self.tool_mode_changed.emit(mode)

    def clear_selection(self) -> None:
        if not self._selected_words and not self._selection_items:
            return
        self._selected_words = []
        for item in self._selection_items:
            self._scene.removeItem(item)
        self._selection_items = []
        self._selection_anchor = None
        self.selection_changed.emit("")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._tool_mode == ToolMode.SELECT and event.button() == Qt.MouseButton.LeftButton:
            self.clear_selection()
            self._selection_anchor = self.mapToScene(event.position().toPoint())
            event.accept()
            return
        if self._tool_mode == ToolMode.REDACTION and event.button() == Qt.MouseButton.LeftButton:
            self._redaction_anchor = self.mapToScene(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._tool_mode == ToolMode.SELECT and self._selection_anchor is not None:
            current = self.mapToScene(event.position().toPoint())
            self._update_selection_from_drag(self._selection_anchor, current)
            event.accept()
            return
        if self._tool_mode == ToolMode.REDACTION and self._redaction_anchor is not None:
            current = self.mapToScene(event.position().toPoint())
            self._update_redaction_overlay(self._redaction_anchor, current)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if (
            self._tool_mode == ToolMode.SELECT
            and self._selection_anchor is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._selection_anchor = None
            self.selection_changed.emit(self.selected_text)
            event.accept()
            return
        if (
            self._tool_mode == ToolMode.REDACTION
            and self._redaction_anchor is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            current = self.mapToScene(event.position().toPoint())
            self._commit_redaction_drag(self._redaction_anchor, current)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _update_selection_from_drag(self, anchor: QPointF, current: QPointF) -> None:
        adapter = self._page_cache.adapter
        if adapter is None or self._page_count == 0:
            return
        if self._view_mode != ViewMode.SINGLE_PAGE:
            return
        x0 = min(anchor.x(), current.x()) / _RENDER_SCALE
        y0 = min(anchor.y(), current.y()) / _RENDER_SCALE
        x1 = max(anchor.x(), current.x()) / _RENDER_SCALE
        y1 = max(anchor.y(), current.y()) / _RENDER_SCALE
        try:
            words = adapter.extract_words(self._current_page)
        except Exception:
            return
        overlapping = [w for w in words if w.x0 < x1 and w.x1 > x0 and w.y0 < y1 and w.y1 > y0]
        if overlapping == self._selected_words:
            return
        self._selected_words = overlapping
        self._refresh_selection_overlay()

    def _refresh_selection_overlay(self) -> None:
        for item in self._selection_items:
            self._scene.removeItem(item)
        self._selection_items = []
        for w in self._selected_words:
            polygon = QPolygonF(
                [
                    QPointF(w.x0 * _RENDER_SCALE, w.y0 * _RENDER_SCALE),
                    QPointF(w.x1 * _RENDER_SCALE, w.y0 * _RENDER_SCALE),
                    QPointF(w.x1 * _RENDER_SCALE, w.y1 * _RENDER_SCALE),
                    QPointF(w.x0 * _RENDER_SCALE, w.y1 * _RENDER_SCALE),
                ]
            )
            item = QGraphicsPolygonItem(polygon)
            item.setBrush(QBrush(_HIGHLIGHT_SELECTION))
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setZValue(1.0)
            self._scene.addItem(item)
            self._selection_items.append(item)

    def _update_redaction_overlay(self, anchor: QPointF, current: QPointF) -> None:
        """PR 12: redraw the pending-redaction rectangle during a drag.

        Uses scene coordinates directly (no page-space conversion
        needed for the visual overlay). Creates the QGraphicsRectItem
        on first move; updates its rect thereafter. Removed by
        ``_commit_redaction_drag`` or by cancellation (Escape).
        """
        x0 = min(anchor.x(), current.x())
        y0 = min(anchor.y(), current.y())
        x1 = max(anchor.x(), current.x())
        y1 = max(anchor.y(), current.y())
        w = x1 - x0
        h = y1 - y0
        if self._redaction_temp_item is None:
            item = QGraphicsRectItem(x0, y0, w, h)
            item.setBrush(QBrush(_REDACTION_PENDING))
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setZValue(2.0)
            self._scene.addItem(item)
            self._redaction_temp_item = item
        else:
            self._redaction_temp_item.setRect(x0, y0, w, h)

    def _commit_redaction_drag(self, anchor: QPointF, current: QPointF) -> None:
        """PR 12: convert scene coords to page-space + emit redaction_requested.

        Only single-page view mode is supported (mirroring the
        text-select constraint). Drags smaller than 5x5 scene
        pixels are treated as accidental clicks and ignored.
        Removes the temporary overlay item.
        """
        # Always release the anchor + temp item, even if we bail
        # out below -- otherwise a bad drag leaves the temp item
        # visible forever.
        self._redaction_anchor = None
        if self._redaction_temp_item is not None:
            self._scene.removeItem(self._redaction_temp_item)
            self._redaction_temp_item = None

        if self._page_count == 0:
            return
        w = abs(anchor.x() - current.x())
        h = abs(anchor.y() - current.y())
        if w < 5 or h < 5:
            return

        # PR 17.6: continuous-mode drag support. In single-page mode the
        # scene contains only the current page, so scene coords == page
        # coords (modulo _RENDER_SCALE). In continuous mode we need to
        # (a) identify which page the drag ANCHORED on (that's the page
        # the mark belongs to), (b) subtract the page's scene y-offset
        # to get page-local coords, and (c) clamp the drag END to that
        # page's bounds so drags spanning multiple pages stay on the
        # starting page.
        if self._view_mode == ViewMode.SINGLE_PAGE:
            target_page = self._current_page
            y_offset = 0.0
            page_bottom_scene = float("inf")
        else:
            target_page = self._page_at_scene_y(anchor.y())
            if not (0 <= target_page < len(self._page_offsets)):
                return
            y_offset = self._page_offsets[target_page]
            if target_page < len(self._pixmap_items):
                pixmap_h = float(self._pixmap_items[target_page].boundingRect().height())
                page_bottom_scene = y_offset + pixmap_h
            else:
                page_bottom_scene = float("inf")

        # Clamp current.y() to the starting page's scene-y range.
        current_y_clamped = min(max(current.y(), y_offset), page_bottom_scene)

        # Convert scene -> page-space (PDF points). Scene is rendered
        # at _RENDER_SCALE, so divide.
        x0 = min(anchor.x(), current.x()) / _RENDER_SCALE
        y0 = (min(anchor.y(), current_y_clamped) - y_offset) / _RENDER_SCALE
        x1 = max(anchor.x(), current.x()) / _RENDER_SCALE
        y1 = (max(anchor.y(), current_y_clamped) - y_offset) / _RENDER_SCALE
        self.redaction_requested.emit(target_page, (x0, y0, x1, y1))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # PR 12: Escape cancels a pending redaction drag.
        if event.key() == Qt.Key.Key_Escape and self._redaction_anchor is not None:
            self._redaction_anchor = None
            if self._redaction_temp_item is not None:
                self._scene.removeItem(self._redaction_temp_item)
                self._redaction_temp_item = None
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        """Right-click context menu. Always available regardless of
        tool mode -- Copy / Extract on a selection are useful even if
        the user happened to make the selection then switched modes.
        Both actions are disabled when no text is selected."""
        has_selection = bool(self._selected_words)
        menu = QMenu(self)
        copy_action = menu.addAction("&Copy")
        copy_action.setEnabled(has_selection)
        copy_action.triggered.connect(self.copy_requested.emit)
        extract_action = menu.addAction("&Extract Selection to File...")
        extract_action.setEnabled(has_selection)
        extract_action.triggered.connect(self.extract_selection_requested.emit)
        # PR 12.1: text-selection redaction.
        redact_action = menu.addAction("Redact &Selection")
        redact_action.setEnabled(has_selection)
        redact_action.triggered.connect(self._on_redact_selection)

        # PR 12.5 (redefined by PR 14b): hit-test click position against
        # pending redaction marks on the current page. If we hit one, offer
        # Edit / Remove -- scoped to the mark's group. Menu labels adapt
        # based on group size (singleton -> "This Mark", many -> "This Group").
        hit = self._hit_test_redaction(self.mapToScene(event.pos()))
        if hit is not None:
            menu.addSeparator()
            page_index, redaction_index = hit
            group_size = self._resolve_group_size_for_hit(page_index, redaction_index)
            if group_size <= 1:
                edit_label = "&Edit This Mark..."
                remove_label = "&Remove This Mark"
            else:
                edit_label = f"&Edit This Group... ({group_size} marks)"
                remove_label = f"&Remove This Group ({group_size} marks)"
            edit_action = menu.addAction(edit_label)
            edit_action.triggered.connect(
                lambda: self.edit_group_requested.emit(page_index, redaction_index)
            )
            remove_action = menu.addAction(remove_label)
            remove_action.triggered.connect(
                lambda: self.remove_mark_requested.emit(page_index, redaction_index)
            )
        menu.exec(event.globalPos())

    def _on_redact_selection(self) -> None:
        """PR 12.1: package current selection + emit redact_selection_requested."""
        if not self._selected_words:
            return
        self.redact_selection_requested.emit(self._current_page, list(self._selected_words))

    def _hit_test_redaction(self, scene_pos) -> tuple[int, int] | None:
        """PR 12.5: return (page_index, redaction_index) if scene_pos hits
        a pending redaction on the current page, else None.

        Scene coordinates are converted to page-space by dividing by
        ``_RENDER_SCALE`` (same convention as ``_commit_redaction_drag``).
        Overlapping marks return the last-added match (topmost visually).
        Only single-page mode is supported -- matches the mode gate on
        the redaction drag interaction.
        """
        adapter = self._page_cache.adapter
        if adapter is None or self._page_count == 0:
            return None
        # PR 17.6: identify the page under the click. Single-page: current.
        # Continuous: derive from scene y via _page_at_scene_y.
        if self._view_mode == ViewMode.SINGLE_PAGE:
            target_page = self._current_page
            y_offset = 0.0
        else:
            target_page = self._page_at_scene_y(scene_pos.y())
            if not (0 <= target_page < len(self._page_offsets)):
                return None
            y_offset = self._page_offsets[target_page]

        # Page-space point (subtract page's scene y-offset first)
        px = scene_pos.x() / _RENDER_SCALE
        py = (scene_pos.y() - y_offset) / _RENDER_SCALE
        # Walk pending marks on the current page
        try:
            all_marks = adapter.list_redactions()
        except Exception:
            return None
        # Filter to current page + assign 0-based per-page indices
        page_marks: list[tuple[int, tuple[float, float, float, float]]] = []
        for r in all_marks:
            if r.page_index != target_page:
                continue
            page_marks.append((len(page_marks), r.rect))
        if not page_marks:
            return None
        # Reverse-iterate to prefer the last-added mark on overlap.
        for local_index, (x0, y0, x1, y1) in reversed(page_marks):
            if x0 <= px <= x1 and y0 <= py <= y1:
                return (target_page, local_index)
        return None

    def _resolve_group_size_for_hit(self, page_index: int, redaction_index: int) -> int:
        """PR 14b: return the number of marks in the group containing
        the given mark, or 1 if not resolvable.

        Uses ``list_redactions_grouped()`` to find the group whose marks
        include the target. Failure modes (adapter missing, mark index
        out of range) default to 1 so the menu falls back to
        "This Mark" labels -- always safe.
        """
        adapter = self._page_cache.adapter
        if adapter is None:
            return 1
        try:
            all_pending = adapter.list_redactions()
        except Exception:
            return 1
        # Filter to this page and pick the target
        page_marks = [m for m in all_pending if m.page_index == page_index]
        if not (0 <= redaction_index < len(page_marks)):
            return 1
        target = page_marks[redaction_index]
        # Now find which group contains this mark
        try:
            groups = adapter.list_redactions_grouped()
        except Exception:
            return 1
        for g in groups:
            for m in g.marks:
                if m.page_index == target.page_index and m.rect == target.rect:
                    return g.count
        return 1

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

"""Diff pane widget (PR 17a).

Renders one document in a scrollable strip with word-level highlight
overlays for use inside DiffView. This is a lightweight renderer that
does NOT reuse PageView (which is designed for interactive navigation);
DiffView needs a simpler, purely read-only view of two documents.

Each page is rendered to a QPixmap once, decorated with colored
rectangles at highlighted word bboxes, and displayed in a QLabel.
All page QLabels are stacked vertically in a QScrollArea. Sync
scroll is coordinated by DiffView via the exposed
``verticalScrollBar()``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter


class DiffPane(QScrollArea):
    """One side of the DiffView -- a scrollable single-doc renderer with highlights.

    Args:
        adapter: adapter with a document open. Must remain open while the
            pane is alive.
        highlight_color: RGBA tuple used for highlight rectangles. Typical
            values: (255, 200, 200, 128) for deletions (light red),
            (200, 255, 200, 128) for insertions (light green).
        zoom: render zoom factor (default 1.0 = 72dpi PDF pt to pixel).
    """

    scroll_changed = Signal(int)
    h_scroll_changed = Signal(int)

    def __init__(
        self,
        adapter: PyMuPDFAdapter,
        highlight_color: tuple[int, int, int, int] = (255, 200, 200, 128),
        zoom: float = 1.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._adapter = adapter
        self._highlight_color = highlight_color
        self._zoom = zoom
        # WordRefs whose bboxes should be highlighted; grouped per-page
        # for efficient repaint. Two layers:
        # - base: all changed words in this pane
        # - current: the word(s) of the currently-navigated diff (drawn
        #   on top with a stronger color + outline).
        self._highlights_per_page: dict[int, list[tuple[float, float, float, float]]] = {}
        self._current_bboxes_per_page: dict[int, list[tuple[float, float, float, float]]] = {}
        # Base (un-highlighted) pixmaps kept for cheap re-highlight
        self._base_pixmaps: list[QPixmap] = []
        self._page_labels: list[QLabel] = []

        self._build_ui()
        self.verticalScrollBar().valueChanged.connect(self.scroll_changed)
        self.horizontalScrollBar().valueChanged.connect(self.h_scroll_changed)
        self._render_all_pages()

    def _build_ui(self) -> None:
        self.setWidgetResizable(True)
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(6)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setWidget(self._container)

    def _render_all_pages(self) -> None:
        """Render every page once and store base pixmaps + labels."""
        if self._adapter is None or self._adapter._doc is None:
            return
        page_count = self._adapter._doc.page_count
        for page_index in range(page_count):
            png_bytes = self._adapter.render_page(page_index, zoom=self._zoom)
            pix = QPixmap()
            pix.loadFromData(png_bytes, "PNG")
            self._base_pixmaps.append(pix)
            label = QLabel()
            label.setPixmap(pix)
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._layout.addWidget(label)
            self._page_labels.append(label)

    def set_highlights(
        self,
        bboxes_per_page: dict[int, list[tuple[float, float, float, float]]],
    ) -> None:
        """Update BASE highlights and repaint each page.

        Args:
            bboxes_per_page: mapping ``page_index -> list of (x0,y0,x1,y1)``
                bboxes in PDF coordinates to highlight with the base color.
        """
        self._highlights_per_page = dict(bboxes_per_page)
        self._repaint_all()

    def set_current_highlights(
        self,
        bboxes_per_page: dict[int, list[tuple[float, float, float, float]]],
    ) -> None:
        """Update CURRENT highlights (single navigated diff) and repaint.

        The current-diff bboxes are drawn on top of the base highlights
        with a stronger color and a thin outline so the user can see
        which diff Previous/Next is pointing at.
        """
        self._current_bboxes_per_page = dict(bboxes_per_page)
        self._repaint_all()

    @staticmethod
    def _merge_line_bboxes(
        bboxes: list[tuple[float, float, float, float]],
        y_tolerance: float = 2.0,
    ) -> list[tuple[float, float, float, float]]:
        """Merge adjacent same-line bboxes into fewer larger rectangles.

        Adjacent = close vertical center (within y_tolerance) AND
        horizontally sequential. Vertical extent of each merged box is
        the union of contributing y-ranges; horizontal is (min x0, max x1).
        Wrapping across lines produces separate output boxes.
        """
        if not bboxes:
            return []
        # Sort left-to-right, then top-to-bottom
        sorted_bboxes = sorted(bboxes, key=lambda b: (b[1], b[0]))
        merged: list[list[float]] = []
        for x0, y0, x1, y1 in sorted_bboxes:
            if not merged:
                merged.append([x0, y0, x1, y1])
                continue
            last = merged[-1]
            # Same line if vertical centers are close
            last_center = (last[1] + last[3]) / 2
            this_center = (y0 + y1) / 2
            if abs(last_center - this_center) < y_tolerance + max(last[3] - last[1], y1 - y0) * 0.3:
                # Same line -- extend last
                last[0] = min(last[0], x0)
                last[1] = min(last[1], y0)
                last[2] = max(last[2], x1)
                last[3] = max(last[3], y1)
            else:
                merged.append([x0, y0, x1, y1])
        return [tuple(m) for m in merged]

    def _repaint_all(self) -> None:
        """Rebuild each page label's pixmap with base + current highlights.

        Two layers: base fill for all changed words, then a stronger
        fill with an outline for the currently-navigated diff (if any).
        Pages with neither reuse the base pixmap unchanged.
        """
        from PySide6.QtGui import QPen

        # Current-diff outline uses a high-contrast color (dark blue)
        # that stands out against both red (deletions) and green (insertions).
        # No fill change -- outline alone signals "you are here".
        current_outline = QColor(20, 60, 200, 255)  # bold blue

        for page_index, base_pix in enumerate(self._base_pixmaps):
            if page_index >= len(self._page_labels):
                continue
            base_bboxes = self._highlights_per_page.get(page_index, [])
            current_bboxes = self._current_bboxes_per_page.get(page_index, [])
            if not base_bboxes and not current_bboxes:
                self._page_labels[page_index].setPixmap(base_pix)
                continue
            decorated = QPixmap(base_pix)
            painter = QPainter(decorated)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            # Base layer
            if base_bboxes:
                painter.setBrush(QColor(*self._highlight_color))
                painter.setPen(Qt.PenStyle.NoPen)
                for x0, y0, x1, y1 in base_bboxes:
                    painter.drawRect(
                        int(x0 * self._zoom),
                        int(y0 * self._zoom),
                        int((x1 - x0) * self._zoom),
                        int((y1 - y0) * self._zoom),
                    )
            # Current-diff layer -- thick bold-blue outline, no extra fill.
            # Merge adjacent same-line bboxes so a phrase gets ONE outline
            # box, not one per word. Wrapping across lines still yields
            # separate boxes (one per line).
            if current_bboxes:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                pen = QPen(current_outline)
                pen.setWidth(3)
                painter.setPen(pen)
                margin = 3
                merged = self._merge_line_bboxes(current_bboxes)
                for x0, y0, x1, y1 in merged:
                    painter.drawRect(
                        int(x0 * self._zoom) - margin,
                        int(y0 * self._zoom) - margin,
                        int((x1 - x0) * self._zoom) + 2 * margin,
                        int((y1 - y0) * self._zoom) + 2 * margin,
                    )
            painter.end()
            self._page_labels[page_index].setPixmap(decorated)

    def sync_scroll_to(self, value: int) -> None:
        """Set vertical scroll to ``value``.

        Uses ``_syncing`` guard to avoid recursion; the sibling pane
        will not re-emit its scroll_changed signal when we scroll it.
        See DiffView._on_left_scrolled / _on_right_scrolled for the
        guard on the sender side. This method itself just sets the
        value normally so the scroll area actually scrolls its
        content (blockSignals() prevented the content from moving).
        """
        self.verticalScrollBar().setValue(value)

    def sync_h_scroll_to(self, value: int) -> None:
        """Set horizontal scroll to ``value``. Mirror of sync_scroll_to."""
        self.horizontalScrollBar().setValue(value)

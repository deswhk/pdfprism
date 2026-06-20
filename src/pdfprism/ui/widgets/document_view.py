"""Per-document tab container for the multi-document MainWindow.

Each open document lives in its own DocumentView. The widget owns its
PyMuPDFAdapter, PageCache, PageView, ThumbnailPanel, OutlinePanel, and
SearchService, so per-tab zoom, scroll position, view mode, search
cursor state, thumbnail selection, and outline expansion are all
preserved naturally across tab switches. MainWindow hosts the sidebars
in QStackedWidgets and swaps which DocumentView's panel is visible on
tab change.
"""

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.types import SearchHit
from pdfprism.services.search import SearchService
from pdfprism.ui.page_cache import PageCache
from pdfprism.ui.widgets.outline_panel import OutlinePanel
from pdfprism.ui.widgets.page_view import PageView, ViewMode
from pdfprism.ui.widgets.thumbnail_panel import ThumbnailPanel


class DocumentView(QWidget):
    """One open document and the per-tab widgets that view it.

    Owns: adapter, page cache, page view, thumbnail panel, outline panel,
    search service. The page view is the only one displayed inside this
    widget; the sidebar panels are exposed for MainWindow to host in its
    dock-area QStackedWidgets.

    Per-tab search cursor state lives as public attributes so MainWindow's
    search slots can read and update it directly without per-tab signal
    plumbing.
    """

    # Proxied PageView signals. MainWindow connects to the active tab's
    # proxies on tab switch.
    page_changed = Signal(int)
    zoom_changed = Signal(float)
    view_mode_changed = Signal(ViewMode)

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = path
        self._adapter = PyMuPDFAdapter()
        self._page_cache = PageCache()
        self._page_view = PageView(self._page_cache, self)
        self._thumbnail_panel = ThumbnailPanel(self._page_cache, self)
        self._outline_panel = OutlinePanel(self)
        self._search_service = SearchService(self._adapter)

        # Per-tab search cursor state.
        self.search_hits: list[SearchHit] = []
        self.current_hit_index: int = -1

        # Proxy PageView signals outward.
        self._page_view.page_changed.connect(self.page_changed)
        self._page_view.zoom_changed.connect(self.zoom_changed)
        self._page_view.view_mode_changed.connect(self.view_mode_changed)

        # Internal sidebar wiring — kept inside the tab so MainWindow never
        # has to rewire on tab change.
        self._thumbnail_panel.page_selected.connect(self._page_view.go_to_page)
        self._outline_panel.page_selected.connect(self._page_view.go_to_page)
        self._page_view.page_changed.connect(self._thumbnail_panel.set_current_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._page_view)

    def open(self) -> None:
        """Load the underlying document. Raises PdfPrismError on failure."""
        self._adapter.open(self._path)
        self._page_view.set_adapter(self._adapter)
        self._thumbnail_panel.set_adapter(self._adapter)
        self._outline_panel.set_outline(self._adapter.get_outline())

    def close_document(self) -> None:
        """Release engine resources. Idempotent.

        Distinct from ``QWidget.close``; we cannot override ``close`` because
        Qt uses it for visibility lifecycle.
        """
        self._page_view.clear()
        self._thumbnail_panel.set_adapter(None)
        self._outline_panel.set_outline([])
        self._adapter.close()
        self._page_cache.clear()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def adapter(self) -> PyMuPDFAdapter:
        return self._adapter

    @property
    def page_view(self) -> PageView:
        return self._page_view

    @property
    def thumbnail_panel(self) -> ThumbnailPanel:
        return self._thumbnail_panel

    @property
    def outline_panel(self) -> OutlinePanel:
        return self._outline_panel

    @property
    def search_service(self) -> SearchService:
        return self._search_service

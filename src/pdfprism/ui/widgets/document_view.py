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
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.types import SearchHit
from pdfprism.services.search import SearchService
from pdfprism.ui.page_cache import PageCache
from pdfprism.ui.widgets.organize_panel import OrganizePagesPanel
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

    # Fires whenever the document's modified state flips.
    modified_changed = Signal(bool)

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = path
        self._adapter = PyMuPDFAdapter()
        self._page_cache = PageCache()
        self._page_view = PageView(self._page_cache, self)
        self._thumbnail_panel = ThumbnailPanel(self._page_cache, self)
        self._outline_panel = OutlinePanel(self)
        self._organize_panel = OrganizePagesPanel(self._page_cache, self)
        self._search_service = SearchService(self._adapter)

        # Per-tab search cursor state.
        self.search_hits: list[SearchHit] = []
        self.current_hit_index: int = -1

        # Modified-state tracking. Adapter holds the truth (is_dirty);
        # this caches the last seen value so we only emit when it flips.
        self._last_modified: bool = False

        # Proxy PageView signals outward.
        self._page_view.page_changed.connect(self.page_changed)
        self._page_view.zoom_changed.connect(self.zoom_changed)
        self._page_view.view_mode_changed.connect(self.view_mode_changed)

        # Internal sidebar wiring — kept inside the tab so MainWindow never
        # has to rewire on tab change.
        self._thumbnail_panel.page_selected.connect(self._page_view.go_to_page)
        self._outline_panel.page_selected.connect(self._page_view.go_to_page)
        self._page_view.page_changed.connect(self._thumbnail_panel.set_current_page)

        # PR 12: redaction drag emits (page_index, rect); we route to
        # RedactionService which creates the pending annotation.
        # No panel rebind dance needed here -- redactions are
        # annotations, not doc-swap operations, so the underlying
        # pymupdf.Document is not closed/reopened.
        self._page_view.redaction_requested.connect(self._on_redaction_requested)

        # PR 12.1: text-selection redaction (right-click on selected text).
        # Payload: (page_index, list of Word objects).
        self._page_view.redact_selection_requested.connect(self._on_redact_selection_requested)

        # PR 12.3: session-level redaction defaults; MainWindow keeps
        # these in sync via ``set_redaction_options`` after the Options
        # dialog is accepted or on app startup from QSettings.
        self._redaction_fill_color: tuple[int, int, int] = (0, 0, 0)
        self._redaction_replacement_text: str | None = None

        # OrganizePagesPanel: panel emits intent, we route through the
        # corresponding mutation methods. Each one already does the
        # adapter mutation + cache clear + panel re-bind + modified-
        # state refresh, so panel + thumbnails + page view all stay
        # in sync after any organize-driven change.
        self._organize_panel.rotate_requested.connect(self._on_organize_rotate)
        self._organize_panel.delete_requested.connect(self._on_organize_delete)
        self._organize_panel.duplicate_requested.connect(self._on_organize_duplicate)
        self._organize_panel.crop_requested.connect(self._on_organize_crop)
        self._organize_panel.extract_requested.connect(self._on_organize_extract)
        self._organize_panel.move_requested.connect(self.move_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._page_view)

    def open(self, password: str | None = None) -> None:
        """Load the underlying document.

        Args:
            password: If the PDF is encrypted, the password to open
                it with. ``None`` (the default) opens unencrypted
                PDFs or raises ``PasswordRequiredError`` on encrypted
                ones. Passing a non-None password on an unencrypted
                PDF is silently ignored by the adapter.

        Raises:
            PdfPrismError: on any open failure (see subclasses).
            PasswordRequiredError: if the PDF is encrypted and the
                supplied password is missing or wrong. Callers can
                retry with a fresh DocumentView + a different
                password.
        """
        self._adapter.open(self._path, password=password)
        self._page_view.set_adapter(self._adapter)
        self._thumbnail_panel.set_adapter(self._adapter)
        self._organize_panel.set_adapter(self._adapter)
        self._outline_panel.set_outline(self._adapter.get_outline())

    def close_document(self) -> None:
        """Release engine resources. Idempotent.

        Distinct from ``QWidget.close``; we cannot override ``close`` because
        Qt uses it for visibility lifecycle.
        """
        self._page_view.clear()
        self._thumbnail_panel.set_adapter(None)
        self._organize_panel.set_adapter(None)
        self._outline_panel.set_outline([])
        self._adapter.close()
        self._page_cache.clear()
        if self._last_modified:
            self._last_modified = False
            self.modified_changed.emit(False)

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
    def organize_panel(self) -> OrganizePagesPanel:
        return self._organize_panel

    @property
    def outline_panel(self) -> OutlinePanel:
        return self._outline_panel

    @property
    def search_service(self) -> SearchService:
        return self._search_service

    # ---- Modified-state API ----------------------------------------------

    @property
    def is_modified(self) -> bool:
        """True when the document has unsaved page-level mutations."""
        return self._adapter.is_dirty

    def _refresh_modified(self) -> None:
        """Re-read the adapter dirty flag; emit if it flipped."""
        now = self._adapter.is_dirty
        if now != self._last_modified:
            self._last_modified = now
            self.modified_changed.emit(now)

    # ---- Page operations -------------------------------------------------
    # All mutations route through here so the modified flag stays in sync
    # and (eventually) so an undo command stack has a single insertion
    # point. UI code (MainWindow, Organize panel) MUST go through these
    # methods rather than touching the adapter directly.

    def rotate_page(self, index: int, degrees: int) -> None:
        self._adapter.rotate_page(index, degrees)
        self._page_cache.clear()
        self._thumbnail_panel.set_adapter(self._adapter)
        self._organize_panel.set_adapter(self._adapter)
        self._page_view.set_adapter(self._adapter)
        self._refresh_modified()

    def delete_pages(self, indices: list[int]) -> None:
        self._adapter.delete_pages(indices)
        self._page_cache.clear()
        self._thumbnail_panel.set_adapter(self._adapter)
        self._organize_panel.set_adapter(self._adapter)
        self._page_view.set_adapter(self._adapter)
        self._refresh_modified()

    def insert_blank_page(self, index: int, width: float, height: float) -> None:
        self._adapter.insert_blank_page(index, width, height)
        self._page_cache.clear()
        self._thumbnail_panel.set_adapter(self._adapter)
        self._organize_panel.set_adapter(self._adapter)
        self._page_view.set_adapter(self._adapter)
        self._refresh_modified()

    def duplicate_page(self, index: int) -> None:
        self._adapter.duplicate_page(index)
        self._page_cache.clear()
        self._thumbnail_panel.set_adapter(self._adapter)
        self._organize_panel.set_adapter(self._adapter)
        self._page_view.set_adapter(self._adapter)
        self._refresh_modified()

    def move_page(self, from_index: int, to_index: int) -> None:
        self._adapter.move_page(from_index, to_index)
        self._page_cache.clear()
        self._thumbnail_panel.set_adapter(self._adapter)
        self._organize_panel.set_adapter(self._adapter)
        self._page_view.set_adapter(self._adapter)
        self._refresh_modified()

    def crop_page(
        self,
        index: int,
        margins: tuple[float, float, float, float],
    ) -> None:
        self._adapter.crop_page(index, margins)
        self._page_cache.clear()
        self._thumbnail_panel.set_adapter(self._adapter)
        self._organize_panel.set_adapter(self._adapter)
        self._page_view.set_adapter(self._adapter)
        self._refresh_modified()

    def insert_from(
        self,
        source_path: Path,
        from_index: int,
        to_index: int,
        at_index: int,
    ) -> None:
        """Insert pages from another PDF on disk into this document."""
        from pdfprism.services.pages import PageService

        PageService(self._adapter).insert_from(source_path, from_index, to_index, at_index)
        self._page_cache.clear()
        self._thumbnail_panel.set_adapter(self._adapter)
        self._organize_panel.set_adapter(self._adapter)
        self._page_view.set_adapter(self._adapter)
        self._refresh_modified()

    # ---- Organize-panel handlers (PR 9) ----------------------------

    def _on_organize_rotate(self, indices: list[int], degrees: int) -> None:
        """Rotate each indexed page; order does not matter for rotation."""
        for i in indices:
            self._adapter.rotate_page(i, degrees)
        self._page_cache.clear()
        self._thumbnail_panel.set_adapter(self._adapter)
        self._organize_panel.set_adapter(self._adapter)
        self._page_view.set_adapter(self._adapter)
        self._refresh_modified()

    def _on_organize_delete(self, indices: list[int]) -> None:
        """Delete the selected pages (adapter primitive takes a list)."""
        self.delete_pages(indices)

    def _on_organize_duplicate(self, indices: list[int]) -> None:
        """Duplicate each selected page; iterate in reverse so indices stay valid."""
        for i in sorted(indices, reverse=True):
            self._adapter.duplicate_page(i)
        self._page_cache.clear()
        self._thumbnail_panel.set_adapter(self._adapter)
        self._organize_panel.set_adapter(self._adapter)
        self._page_view.set_adapter(self._adapter)
        self._refresh_modified()

    def _on_organize_crop(
        self,
        indices: list[int],
        margins: tuple[float, float, float, float],
    ) -> None:
        """Apply the same crop margins to each selected page.

        Order-independent: each page's cropbox is computed
        independently, so forward iteration is fine. Empty
        ``indices`` is a safe no-op (no adapter calls, no
        rebind, no dirty flag change).

        Margin validation is the dialog's responsibility;
        adapter-level failures (e.g., zero-area crop) propagate
        the underlying exception rather than being swallowed.
        """
        if not indices:
            return
        for i in indices:
            self._adapter.crop_page(i, margins)
        self._page_cache.clear()
        self._thumbnail_panel.set_adapter(self._adapter)
        self._organize_panel.set_adapter(self._adapter)
        self._page_view.set_adapter(self._adapter)
        self._refresh_modified()

    def _on_organize_extract(
        self,
        indices: list[int],
        output_path: Path,
    ) -> None:
        """Extract the selected pages to a new PDF file.

        Read-only against the source document: no cache
        clear, no panel rebind, no dirty flag change.
        Symmetric with PR 8.5's extract_to_file which also
        leaves the source untouched.

        Empty ``indices`` is defensively silent -- the panel
        already refuses to emit for empty selections, but
        being explicit avoids relying on that invariant.
        """
        if not indices:
            return
        from pdfprism.services.pages import PageService

        service = PageService(self._adapter)
        service.extract_pages_to_file(indices, output_path)

    # ---- Save ------------------------------------------------------------

    def save(self) -> None:
        """Save in-place to the path the document was opened from."""
        self._adapter.save()
        self._refresh_modified()

    def save_as(self, path: Path) -> None:
        """Save to a new path; subsequent in-place saves go to this path."""
        self._adapter.save(path)
        self._path = path
        self._refresh_modified()

    # PR 10.5: encryption operations (delegate to SecurityService)

    def set_password(self, password: str) -> None:
        """Add a password to an unencrypted document (in-place save)."""
        from pdfprism.services.security import SecurityService

        # PR 10.5: encryption changes trigger an in-place adapter
        # save that closes and reopens the underlying pymupdf.Document.
        # Any pymupdf.Page handles held by the panels become stale --
        # a Qt paint event landing between close and reopen produces
        # 'aes padding out of range' / 'syntax error in content stream'
        # errors as MuPDF decrypts with the old crypt keys. Fix: detach
        # + clear cache BEFORE the save so no widget holds a live page
        # handle during the swap; rebind afterwards.
        self._thumbnail_panel.set_adapter(None)
        self._organize_panel.set_adapter(None)
        self._page_view.set_adapter(None)
        self._page_cache.clear()
        # PR 10.5: flush pending Qt paint events against the just-
        # detached (empty) panels. Any repaints queued before the
        # detach otherwise fire DURING the adapter's in-place save,
        # touching pymupdf.Page handles captured before the detach
        # (they leak past the None-binding via already-queued paints
        # in Qt's event queue). Draining them here means any late
        # repaint sees the panels in their empty state.
        QApplication.processEvents()

        SecurityService(self._adapter).set_password(password)

        # Rebind panels to the fresh adapter (its _doc is the
        # newly-opened post-save Document).
        self._thumbnail_panel.set_adapter(self._adapter)
        self._organize_panel.set_adapter(self._adapter)
        self._page_view.set_adapter(self._adapter)
        self._refresh_modified()

    def change_password(self, password: str) -> None:
        """Change the password on an already-encrypted document (in-place)."""
        from pdfprism.services.security import SecurityService

        # PR 10.5: encryption changes trigger an in-place adapter
        # save that closes and reopens the underlying pymupdf.Document.
        # Any pymupdf.Page handles held by the panels become stale --
        # a Qt paint event landing between close and reopen produces
        # 'aes padding out of range' / 'syntax error in content stream'
        # errors as MuPDF decrypts with the old crypt keys. Fix: detach
        # + clear cache BEFORE the save so no widget holds a live page
        # handle during the swap; rebind afterwards.
        self._thumbnail_panel.set_adapter(None)
        self._organize_panel.set_adapter(None)
        self._page_view.set_adapter(None)
        self._page_cache.clear()
        # PR 10.5: flush pending Qt paint events against the just-
        # detached (empty) panels. Any repaints queued before the
        # detach otherwise fire DURING the adapter's in-place save,
        # touching pymupdf.Page handles captured before the detach
        # (they leak past the None-binding via already-queued paints
        # in Qt's event queue). Draining them here means any late
        # repaint sees the panels in their empty state.
        QApplication.processEvents()

        SecurityService(self._adapter).change_password(password)

        # Rebind panels to the fresh adapter (its _doc is the
        # newly-opened post-save Document).
        self._thumbnail_panel.set_adapter(self._adapter)
        self._organize_panel.set_adapter(self._adapter)
        self._page_view.set_adapter(self._adapter)
        self._refresh_modified()

    def remove_password(self) -> None:
        """Remove the password from an encrypted document (in-place)."""
        from pdfprism.services.security import SecurityService

        # PR 10.5: encryption changes trigger an in-place adapter
        # save that closes and reopens the underlying pymupdf.Document.
        # Any pymupdf.Page handles held by the panels become stale --
        # a Qt paint event landing between close and reopen produces
        # 'aes padding out of range' / 'syntax error in content stream'
        # errors as MuPDF decrypts with the old crypt keys. Fix: detach
        # + clear cache BEFORE the save so no widget holds a live page
        # handle during the swap; rebind afterwards.
        self._thumbnail_panel.set_adapter(None)
        self._organize_panel.set_adapter(None)
        self._page_view.set_adapter(None)
        self._page_cache.clear()
        # PR 10.5: flush pending Qt paint events against the just-
        # detached (empty) panels. Any repaints queued before the
        # detach otherwise fire DURING the adapter's in-place save,
        # touching pymupdf.Page handles captured before the detach
        # (they leak past the None-binding via already-queued paints
        # in Qt's event queue). Draining them here means any late
        # repaint sees the panels in their empty state.
        QApplication.processEvents()

        SecurityService(self._adapter).remove_password()

        # Rebind panels to the fresh adapter (its _doc is the
        # newly-opened post-save Document).
        self._thumbnail_panel.set_adapter(self._adapter)
        self._organize_panel.set_adapter(self._adapter)
        self._page_view.set_adapter(self._adapter)
        self._refresh_modified()

    # ---- PR 12: redactions --------------------------------------------

    def _on_redaction_requested(self, page_index: int, rect: tuple) -> None:
        """Slot: PageView redaction drag -> create annotation."""
        from pdfprism.services.redaction import RedactionService

        RedactionService(
            self._adapter,
            fill_color=self._redaction_fill_color,
            replacement_text=self._redaction_replacement_text,
        ).add_redaction(page_index=page_index, rect=rect)
        self._refresh_modified()
        # Re-render the page so the new annotation is visible.
        # The page_cache holds a rendered pixmap that does NOT
        # include the annotation we just added; invalidate and
        # trigger a repaint via a set_adapter rebind.
        self._page_cache.clear()
        self._page_view.set_adapter(self._adapter)
        self._thumbnail_panel.set_adapter(self._adapter)

    def _on_redact_selection_requested(self, page_index: int, words: list) -> None:
        """PR 12.1: Slot -- selected-text redaction. Per-word rects."""
        from pdfprism.services.redaction import RedactionService

        count = RedactionService(
            self._adapter,
            fill_color=self._redaction_fill_color,
            replacement_text=self._redaction_replacement_text,
        ).redact_words(page_index, words)
        if not count:
            return
        # Clear the text selection now that we've committed it as redactions.
        self._page_view.clear_selection()
        self._refresh_modified()
        # Re-render since new annotations changed the doc.
        self._page_cache.clear()
        self._page_view.set_adapter(self._adapter)
        self._thumbnail_panel.set_adapter(self._adapter)

    def set_redaction_options(
        self,
        fill_color: tuple[int, int, int],
        replacement_text: str | None,
    ) -> None:
        """PR 12.3: apply session-level redaction defaults from MainWindow."""
        self._redaction_fill_color = fill_color
        self._redaction_replacement_text = replacement_text

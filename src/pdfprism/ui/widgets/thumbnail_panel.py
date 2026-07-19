"""Thumbnail panel showing one small pixmap per page.

The panel is backed by a thin ``QAbstractListModel`` that pulls pixmaps from
a shared ``PageCache``. Clicking a row emits ``page_selected(int)``; external
selection changes (e.g., ``PageView`` advancing) are propagated in via
``set_current_page(int)`` so the highlighted thumbnail stays in sync.
"""

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtWidgets import QAbstractItemView, QListView, QWidget

from pdfprism.core.document import DocumentAdapter
from pdfprism.ui.page_cache import PageCache

_THUMBNAIL_ZOOM = 0.25
_ICON_SIZE = QSize(160, 220)


class ThumbnailModel(QAbstractListModel):
    """List model exposing one row per PDF page."""

    def __init__(
        self,
        cache: PageCache,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._cache = cache
        self._page_count = 0

    def set_adapter(self, adapter: DocumentAdapter | None) -> None:
        """Reset the model to reflect the new (or empty) document."""
        self.beginResetModel()
        self._page_count = adapter.page_count if adapter is not None else 0
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        if parent.isValid():
            return 0
        return self._page_count

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid() or not (0 <= index.row() < self._page_count):
            return None
        if role == Qt.ItemDataRole.DecorationRole:
            return self._cache.get_or_render(index.row(), _THUMBNAIL_ZOOM)
        if role == Qt.ItemDataRole.DisplayRole:
            return f"Page {index.row() + 1}"
        return None


class ThumbnailPanel(QListView):
    """Vertical list of page thumbnails. Clicking a row emits page_selected."""

    page_selected = Signal(int)

    def __init__(
        self,
        cache: PageCache,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cache = cache
        self._model = ThumbnailModel(cache, self)
        self.setModel(self._model)

        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.TopToBottom)
        self.setWrapping(False)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setIconSize(_ICON_SIZE)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # PR 17.5: thumbnail visibility polish -- borders + selection highlight.
        # Colors chosen to read well in both light and dark themes:
        # - Each item gets a subtle semi-transparent gray border so pages
        #   are visually separated instead of running together
        # - Selected item gets a 3px accent-blue border + light blue tint
        #   background so the current page is unmistakable in either theme
        # - Hover gets a soft gray tint to signal clickability
        self.setSpacing(6)
        self.setStyleSheet(
            "QListView::item {"
            "    border: 1px solid rgba(128, 128, 128, 80);"
            "    border-radius: 4px;"
            "    padding: 4px;"
            "    margin: 0px;"
            "}"
            "QListView::item:hover {"
            "    background-color: rgba(59, 130, 246, 60);"
            "}"
            "QListView::item:selected {"
            "    border: 3px solid #3b82f6;"
            "    background-color: rgba(59, 130, 246, 40);"
            "}"
            "QListView::item:selected:active {"
            "    border: 3px solid #3b82f6;"
            "    background-color: rgba(59, 130, 246, 40);"
            "}"
        )

        self.clicked.connect(self._on_clicked)

    def set_adapter(self, adapter: DocumentAdapter | None) -> None:
        """Bind a new document. Resets the cache and the model."""
        self._cache.set_adapter(adapter)
        self._model.set_adapter(adapter)

    def set_current_page(self, page_index: int) -> None:
        """Highlight the row for ``page_index`` and scroll it into view."""
        if not (0 <= page_index < self._model.rowCount()):
            return
        idx = self._model.index(page_index, 0)
        if idx.isValid():
            self.setCurrentIndex(idx)
            self.scrollTo(idx, QAbstractItemView.ScrollHint.EnsureVisible)

    def _on_clicked(self, index: QModelIndex) -> None:
        if index.isValid():
            self.page_selected.emit(index.row())

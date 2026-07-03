"""Organize Pages panel: a grid of larger thumbnails with multi-select and drag-to-reorder.

Parallels ``ThumbnailPanel`` (PR 5, navigation use) but is configured
for editing workflows: ``IconMode`` with ``LeftToRight`` wrapping flow
gives a grid layout, ``ExtendedSelection`` enables Ctrl+click and
Shift+click for multi-select, and ``InternalMove`` drag-drop mode
(activated in a later sub-step) supports drag-to-reorder.

The model is intentionally near-identical to ``ThumbnailModel``; we
do not share it because the panels have different lifecycles and the
selection semantics are different enough that one class juggling both
would be a mess.
"""

from PySide6.QtCore import (
    QAbstractListModel,
    QItemSelection,
    QModelIndex,
    QObject,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QListView,
    QMenu,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pdfprism.core.document import DocumentAdapter
from pdfprism.ui.page_cache import PageCache

# Organize panel uses larger thumbnails than ThumbnailPanel because
# users need to identify pages well enough to reorder them confidently.
_ORGANIZE_ZOOM = 0.30
_ICON_SIZE = QSize(180, 240)


class OrganizeModel(QAbstractListModel):
    """List model exposing one row per PDF page, used by the grid view."""

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
            return self._cache.get_or_render(index.row(), _ORGANIZE_ZOOM)
        if role == Qt.ItemDataRole.DisplayRole:
            return f"Page {index.row() + 1}"
        return None


class OrganizePanel(QListView):
    """Grid of page thumbnails supporting multi-select and (later) drag-reorder."""

    # Emitted whenever the selection changes; argument is the current list
    # of selected 0-based page indices, sorted.
    selection_changed = Signal(list)

    # Emitted when the user invokes a page operation against the
    # current selection. The host (DocumentView via MainWindow)
    # owns the actual mutation: it routes to the adapter and then
    # re-binds every panel/view so all sibling widgets stay in sync.
    # Argument is the list of 0-based page indices to operate on,
    # captured at signal-emission time (so subsequent re-bind that
    # clears selection doesn't lose the intent).
    rotate_requested = Signal(list, int)  # indices, degrees
    delete_requested = Signal(list)
    duplicate_requested = Signal(list)

    # Emitted on drag-to-reorder. Arguments are the source and
    # destination 0-based page indices in DocumentView.move_page
    # contract (destination is the desired POST-removal target
    # position). The host calls move_page and the panel is
    # re-bound; we never touch Qt's model directly.
    move_requested = Signal(int, int)  # from_index, to_index

    # PR 9.5: crop-on-selection. Argument is the list of 0-based
    # page indices to crop, followed by the (top, right, bottom, left)
    # margin tuple in PDF points. Emitted by request_crop() after
    # the CropDialog closes with Accepted.
    crop_requested = Signal(list, tuple)  # indices, margins

    # PR 9.5: extract-selection-to-file. Argument is the list of
    # 0-based page indices to extract (order preserved, duplicates
    # kept), followed by the resolved output ``Path``. Emitted by
    # request_extract() after the file dialog closes with a chosen
    # path. ``object`` typing covers pathlib.Path in the Signal.
    extract_requested = Signal(list, object)  # indices, output_path

    def __init__(
        self,
        cache: PageCache,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cache = cache
        self._adapter: DocumentAdapter | None = None
        self._model = OrganizeModel(cache, self)
        self.setModel(self._model)

        # IconMode + LeftToRight + Wrapping = grid layout.
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setIconSize(_ICON_SIZE)
        self.setGridSize(QSize(_ICON_SIZE.width() + 20, _ICON_SIZE.height() + 30))

        # Multi-select with Ctrl/Shift modifiers; Ctrl+A works out of the box.
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)

        # Drag-to-reorder. We deliberately use DragDrop (not
        # InternalMove) and intercept dropEvent so Qt never moves
        # a row in its own model; the host owns the mutation via
        # the adapter and re-binds afterwards.
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

        # Forward Qt's selection-changed model signal to our public API.
        self.selectionModel().selectionChanged.connect(self._on_selection_changed)

    # ---- Public API ---------------------------------------------------------

    def set_adapter(self, adapter: DocumentAdapter | None) -> None:
        """Bind a new document. Resets the cache and the model."""
        self._adapter = adapter
        self._cache.set_adapter(adapter)
        self._model.set_adapter(adapter)

    @property
    def selected_indices(self) -> list[int]:
        """Return sorted list of selected 0-based page indices."""
        sm = self.selectionModel()
        if sm is None:
            return []
        return sorted(idx.row() for idx in sm.selectedIndexes() if idx.isValid())

    # ---- Signal plumbing ----------------------------------------------------

    # ---- Drag-and-drop -------------------------------------------------------

    @staticmethod
    def _qt_drop_to_move_page(from_row: int, dest_row: int) -> tuple[int, int] | None:
        """Translate Qt drop semantics to DocumentView.move_page contract.

        Qt's drop indicator uses *insertion* coordinates (the new
        item appears *before* ``dest_row`` of the *current* list).
        DocumentView.move_page uses *post-removal* target index.
        For backward moves these coincide; for forward moves the
        target shifts down by one.
        """
        if from_row == dest_row:
            return None
        if from_row < dest_row:
            return (from_row, dest_row - 1)
        return (from_row, dest_row)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        """Intercept drop: emit move_requested and ignore so Qt does no move."""
        selected = self.selectedIndexes()
        if not selected:
            event.ignore()
            return
        # PR 9 v1 supports single-page drag only. If multi-select
        # is active, only the row the user is dragging moves; the
        # others stay put. Qt's currentIndex tracks the active
        # drag source.
        current = self.currentIndex()
        if not current.isValid():
            event.ignore()
            return
        from_row = current.row()
        # Compute destination row from the drop position.
        target = self.indexAt(event.position().toPoint())
        indicator = self.dropIndicatorPosition()
        n = self._model.rowCount()
        if target.isValid():
            dest_row = target.row()
            if indicator == QAbstractItemView.DropIndicatorPosition.BelowItem:
                dest_row += 1
        else:
            # Dropped on empty viewport area: append at end.
            dest_row = n
        translation = self._qt_drop_to_move_page(from_row, dest_row)
        # Ignore the event so Qt doesn't try to move rows itself.
        event.ignore()
        if translation is not None:
            self.move_requested.emit(*translation)

    def _on_selection_changed(
        self,
        _selected: QItemSelection,
        _deselected: QItemSelection,
    ) -> None:
        self.selection_changed.emit(self.selected_indices)

    # ---- Operation request helpers --------------------------------------

    def request_rotate(self, degrees: int) -> None:
        """Emit ``rotate_requested`` with current selection + degrees."""
        sel = self.selected_indices
        if sel:
            self.rotate_requested.emit(sel, degrees)

    def request_delete(self) -> None:
        """Emit ``delete_requested`` with current selection."""
        sel = self.selected_indices
        if sel:
            self.delete_requested.emit(sel)

    def request_duplicate(self) -> None:
        """Emit ``duplicate_requested`` with current selection."""
        sel = self.selected_indices
        if sel:
            self.duplicate_requested.emit(sel)

    def request_crop(self, margins: tuple[float, float, float, float]) -> None:
        """Emit ``crop_requested`` with current selection + margins."""
        sel = self.selected_indices
        if sel:
            self.crop_requested.emit(sel, margins)

    def request_extract(self, output_path: object) -> None:
        """Emit ``extract_requested`` with current selection + path.

        ``output_path`` is annotated ``object`` because Qt's
        Signal(list, object) marshalling accepts any Python object;
        the receiver treats it as ``pathlib.Path``.
        """
        sel = self.selected_indices
        if sel:
            self.extract_requested.emit(sel, output_path)


class OrganizePagesPanel(QWidget):
    """Composite widget: toolbar above an ``OrganizePanel`` grid.

    This is what MainWindow docks. The bare ``OrganizePanel`` is
    the grid itself; this wrapper adds the toolbar of selection-
    aware actions and a status label showing the selection count.
    All operation signals are re-emitted from the inner grid so
    callers can subscribe without reaching for ``._grid``.
    """

    selection_changed = Signal(list)
    rotate_requested = Signal(list, int)
    delete_requested = Signal(list)
    duplicate_requested = Signal(list)
    move_requested = Signal(int, int)
    crop_requested = Signal(list, tuple)  # PR 9.5
    extract_requested = Signal(list, object)  # PR 9.5

    def __init__(
        self,
        cache: PageCache,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._grid = OrganizePanel(cache, self)
        self._status = QLabel("No selection")

        # ---- Toolbar with selection-aware actions ----------------------
        toolbar = QToolBar("Organize", self)
        toolbar.setIconSize(QSize(20, 20))

        self.act_rotate_right = QAction("Rotate &Right", self)
        self.act_rotate_right.setToolTip("Rotate selected pages 90° clockwise")
        self.act_rotate_right.triggered.connect(lambda: self._grid.request_rotate(90))
        self.act_rotate_right.setShortcut(QKeySequence("Ctrl+R"))
        self.act_rotate_right.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

        self.act_rotate_left = QAction("Rotate &Left", self)
        self.act_rotate_left.setToolTip("Rotate selected pages 90° counter-clockwise")
        self.act_rotate_left.triggered.connect(lambda: self._grid.request_rotate(270))
        self.act_rotate_left.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self.act_rotate_left.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

        self.act_rotate_180 = QAction("Rotate 180°", self)
        self.act_rotate_180.triggered.connect(lambda: self._grid.request_rotate(180))

        self.act_delete = QAction("&Delete", self)
        self.act_delete.setToolTip("Delete selected pages")
        self.act_delete.triggered.connect(self._grid.request_delete)
        self.act_delete.setShortcut(QKeySequence.StandardKey.Delete)
        self.act_delete.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

        self.act_duplicate = QAction("D&uplicate", self)
        self.act_duplicate.setToolTip("Duplicate selected pages")
        self.act_duplicate.triggered.connect(self._grid.request_duplicate)
        self.act_duplicate.setShortcut(QKeySequence("Ctrl+D"))
        self.act_duplicate.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

        self.act_crop = QAction("&Crop...", self)
        self.act_crop.setToolTip("Crop selected pages with the same margins")
        self.act_crop.triggered.connect(self._on_crop_requested)
        # PR 9.5: no shortcut (Ctrl+K conflicts with common bindings
        # on some Qt platform themes); menu / toolbar-driven only.

        self.act_extract = QAction("&Extract Selection...", self)
        self.act_extract.setToolTip("Save selected pages as a new PDF file")
        self.act_extract.triggered.connect(self._on_extract_requested)
        self.act_extract.setShortcut(QKeySequence("Ctrl+E"))
        self.act_extract.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

        for act in (
            self.act_rotate_right,
            self.act_rotate_left,
            self.act_rotate_180,
            self.act_delete,
            self.act_duplicate,
            self.act_crop,
            self.act_extract,
        ):
            act.setEnabled(False)
            toolbar.addAction(act)

        # ---- Context menu (mirrors toolbar + select-all) ------------------
        self._grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._grid.customContextMenuRequested.connect(self._show_context_menu)

        self.act_select_all = QAction("Select &All", self)
        self.act_select_all.triggered.connect(self._grid.selectAll)
        self.act_select_all.setShortcut(QKeySequence.StandardKey.SelectAll)
        self.act_select_all.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

        # ---- Layout ------------------------------------------------------
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(toolbar)
        layout.addWidget(self._grid, 1)
        layout.addWidget(self._status)

        # ---- Signal plumbing ---------------------------------------------
        self._grid.selection_changed.connect(self._on_selection_changed)
        self._grid.rotate_requested.connect(self.rotate_requested)
        self._grid.delete_requested.connect(self.delete_requested)
        self._grid.duplicate_requested.connect(self.duplicate_requested)
        self._grid.move_requested.connect(self.move_requested)
        self._grid.crop_requested.connect(self.crop_requested)
        self._grid.extract_requested.connect(self.extract_requested)

        for act in (
            self.act_rotate_right,
            self.act_rotate_left,
            self.act_rotate_180,
            self.act_delete,
            self.act_duplicate,
            self.act_crop,
            self.act_extract,
            self.act_select_all,
        ):
            self.addAction(act)

        # Prime the status label and action states.
        self._on_selection_changed([])

    # ---- Public API: delegate to the grid -----------------------------------

    def set_adapter(self, adapter) -> None:
        """Bind a new document."""
        self._grid.set_adapter(adapter)
        # Reset selection visualisation; selection_changed signal
        # already wired to update the status label and buttons.
        self._on_selection_changed([])

    @property
    def selected_indices(self) -> list[int]:
        return self._grid.selected_indices

    @property
    def cache(self) -> PageCache:
        """Public accessor for the shared PageCache used by the grid.

        Exposed so dialogs opened by MainWindow-scope actions
        (e.g., Crop Page) can render previews via the same
        cache used by the panel thumbnails -- avoids a
        redundant rasterisation and keeps the LRU warm.
        """
        return self._grid._cache

    # ---- Selection-driven UI state ------------------------------------------

    def _on_selection_changed(self, indices: list[int]) -> None:
        has = bool(indices)
        for act in (
            self.act_rotate_right,
            self.act_rotate_left,
            self.act_rotate_180,
            self.act_delete,
            self.act_duplicate,
            self.act_crop,
            self.act_extract,
        ):
            act.setEnabled(has)
        total = self._grid._model.rowCount()
        if not has:
            self._status.setText(f"{total} page{'s' if total != 1 else ''}")
        else:
            self._status.setText(f"{len(indices)} of {total} selected")
        self.selection_changed.emit(indices)

    # ---- Context menu --------------------------------------------------------

    def _on_crop_requested(self) -> None:
        """Open CropDialog for the current selection; on Accept,
        emit crop_requested via ``request_crop``.

        For multi-select, the dialog is sized against the
        smallest selected page so the margins stay safe for
        every page in the selection.
        """
        from pdfprism.ui.dialogs.crop import CropDialog

        indices = self._grid.selected_indices
        if not indices:
            return
        adapter = self._grid._adapter
        if adapter is None:
            return
        # Find the smallest page across the selection to bound
        # margins conservatively.
        min_w = float("inf")
        min_h = float("inf")
        for i in indices:
            info = adapter.get_page_info(i)
            min_w = min(min_w, info.width_points)
            min_h = min(min_h, info.height_points)
        dlg = CropDialog(
            page_index=indices[0],  # title shows the first selected page
            page_width=min_w,
            page_height=min_h,
            page_cache=self._grid._cache,
            parent=self,
        )
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._grid.request_crop(dlg.margins)

    @staticmethod
    def _suggest_extract_filename(source_stem: str, indices: list[int]) -> str:
        """Return a filename suggestion for the extract dialog.

        Contiguous indices produce ``<stem>_pages_<from>-<to>.pdf``
        (using 1-based page numbers for the human-facing name).
        Anything else produces ``<stem>_pages_selection.pdf``.
        A single-index selection is trivially contiguous and
        produces ``<stem>_pages_<n>-<n>.pdf`` for consistency.
        """
        if indices and indices == list(range(indices[0], indices[-1] + 1)):
            first = indices[0] + 1
            last = indices[-1] + 1
            return f"{source_stem}_pages_{first}-{last}.pdf"
        return f"{source_stem}_pages_selection.pdf"

    def _on_extract_requested(self) -> None:
        """Open a Save-As dialog for the current selection, then
        emit extract_requested with (indices, output_path).

        No-op if the selection is empty, the adapter is unbound,
        or the user cancels the file dialog.
        """
        from pathlib import Path as _Path

        from PySide6.QtWidgets import QFileDialog

        indices = self._grid.selected_indices
        if not indices:
            return
        adapter = self._grid._adapter
        if adapter is None:
            return
        # Reach for the adapter's stored path to derive a
        # sensible filename stem. This is a small leaky
        # abstraction; a follow-up could lift ``path`` to the
        # DocumentAdapter Protocol.
        adapter_path = getattr(adapter, "_path", None)
        stem = adapter_path.stem if adapter_path is not None else "document"
        suggested_name = self._suggest_extract_filename(stem, indices)
        default_dir = str(adapter_path.parent) if adapter_path is not None else ""
        default_path = f"{default_dir}/{suggested_name}" if default_dir else suggested_name
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Save Selected Pages As",
            default_path,
            "PDF files (*.pdf);;All files (*)",
        )
        if not chosen:
            return
        self._grid.request_extract(_Path(chosen))

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction(self.act_rotate_right)
        menu.addAction(self.act_rotate_left)
        menu.addAction(self.act_rotate_180)
        menu.addSeparator()
        menu.addAction(self.act_duplicate)
        menu.addAction(self.act_delete)
        menu.addSeparator()
        menu.addAction(self.act_crop)
        menu.addAction(self.act_extract)
        menu.addSeparator()
        menu.addAction(self.act_select_all)
        menu.exec(self._grid.viewport().mapToGlobal(pos))

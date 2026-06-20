"""Cross-document search results panel."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from pdfprism.core.types import CrossDocHit


class SearchResultsPanel(QWidget):
    """Tree of cross-document search results, grouped by document.

    Each top-level item is a document showing ``<filename> (N hits)``;
    each child is a hit showing ``Page M`` (1-based). Click on a hit
    emits ``result_selected`` with the hit's index in the flat results
    list, so MainWindow can switch to that tab and jump to the hit.

    Per-hit snippets are intentionally deferred to PR 7 (text extraction)
    so this panel does not depend on any new adapter capability.
    """

    result_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree)

    def set_results(self, results: list[CrossDocHit], doc_titles: list[str]) -> None:
        """Populate the tree, grouping results by ``doc_index``.

        ``doc_titles`` is indexed by ``doc_index``; missing indices fall
        back to a generic ``Document N`` label.
        """
        self._tree.clear()
        if not results:
            return
        by_doc: dict[int, list[tuple[int, CrossDocHit]]] = {}
        for flat_index, r in enumerate(results):
            by_doc.setdefault(r.doc_index, []).append((flat_index, r))
        for doc_index in sorted(by_doc.keys()):
            hits = by_doc[doc_index]
            title = (
                doc_titles[doc_index]
                if 0 <= doc_index < len(doc_titles)
                else f"Document {doc_index}"
            )
            doc_item = QTreeWidgetItem([f"{title} ({len(hits)} hits)"])
            self._tree.addTopLevelItem(doc_item)
            for flat_index, r in hits:
                hit_item = QTreeWidgetItem([f"Page {r.hit.page_index + 1}"])
                hit_item.setData(0, Qt.ItemDataRole.UserRole, flat_index)
                doc_item.addChild(hit_item)
            doc_item.setExpanded(True)

    def clear(self) -> None:
        """Empty the tree."""
        self._tree.clear()

    def set_current(self, index: int) -> None:
        """Select the hit row matching the given flat-list index.

        No-op if the index is not in the tree.
        """
        for i in range(self._tree.topLevelItemCount()):
            doc_item = self._tree.topLevelItem(i)
            for j in range(doc_item.childCount()):
                hit_item = doc_item.child(j)
                if hit_item.data(0, Qt.ItemDataRole.UserRole) == index:
                    self._tree.setCurrentItem(hit_item)
                    return

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        if idx is not None:
            self.result_selected.emit(idx)

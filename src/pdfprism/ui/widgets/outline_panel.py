"""Outline (table of contents) panel.

Renders a PDF's outline as a tree. Clicking an entry emits
``page_selected(int)`` with the entry's 0-based target page. The flat
``list[OutlineItem]`` from the adapter is converted to a tree via a
stack-based pass: for each item, pop nodes whose level is at or below the
new item's level until the stack top is a strict ancestor, then attach.
"""

from dataclasses import dataclass, field

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QObject, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QTreeView, QWidget

from pdfprism.core.types import OutlineItem


@dataclass
class OutlineNode:
    """One node in the outline tree. Children are appended; parent back-ref
    is set at construction time so ``QAbstractItemModel.parent()`` can walk up.
    """

    level: int
    title: str
    page_index: int
    parent: "OutlineNode | None" = None
    children: list["OutlineNode"] = field(default_factory=list)

    def row(self) -> int:
        """0-based position of this node in its parent's children list."""
        if self.parent is None:
            return 0
        return self.parent.children.index(self)


class OutlineModel(QAbstractItemModel):
    """Tree model exposing the outline. Single column (the title)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._root = OutlineNode(level=0, title="", page_index=-1)

    def set_outline(self, items: list[OutlineItem]) -> None:
        """Replace the tree with one built from ``items``."""
        self.beginResetModel()
        self._root = self._build_tree(items)
        self.endResetModel()

    @staticmethod
    def _build_tree(items: list[OutlineItem]) -> OutlineNode:
        root = OutlineNode(level=0, title="", page_index=-1)
        stack: list[OutlineNode] = [root]
        for item in items:
            while len(stack) > 1 and stack[-1].level >= item.level:
                stack.pop()
            node = OutlineNode(
                level=item.level,
                title=item.title,
                page_index=item.page_index,
                parent=stack[-1],
            )
            stack[-1].children.append(node)
            stack.append(node)
        return root

    def _node(self, index: QModelIndex) -> OutlineNode:
        if index.isValid():
            node = index.internalPointer()
            assert isinstance(node, OutlineNode)
            return node
        return self._root

    def page_index_for(self, index: QModelIndex) -> int:
        """Target page (0-based) for ``index``, or -1 if invalid."""
        if not index.isValid():
            return -1
        return self._node(index).page_index

    # -- QAbstractItemModel overrides ----------------------------------------

    def index(
        self,
        row: int,
        column: int,
        parent: QModelIndex = QModelIndex(),  # noqa: B008
    ) -> QModelIndex:
        if column != 0 or row < 0:
            return QModelIndex()
        parent_node = self._node(parent)
        if row >= len(parent_node.children):
            return QModelIndex()
        return self.createIndex(row, column, parent_node.children[row])

    def parent(self, child: QModelIndex = QModelIndex()) -> QModelIndex:  # noqa: B008
        if not child.isValid():
            return QModelIndex()
        node = self._node(child)
        parent_node = node.parent
        if parent_node is None or parent_node is self._root:
            return QModelIndex()
        return self.createIndex(parent_node.row(), 0, parent_node)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        if parent.column() > 0:
            return 0
        return len(self._node(parent).children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, ARG002
        return 1

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._node(index).title
        return None


class OutlinePanel(QTreeView):
    """Tree view of a PDF's outline. Clicking emits ``page_selected``."""

    page_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = OutlineModel(self)
        self.setModel(self._model)
        self.setHeaderHidden(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.clicked.connect(self._on_clicked)

    def set_outline(self, items: list[OutlineItem]) -> None:
        """Replace the outline and expand all nodes."""
        self._model.set_outline(items)
        self.expandAll()

    def _on_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        page = self._model.page_index_for(index)
        if page >= 0:
            self.page_selected.emit(page)

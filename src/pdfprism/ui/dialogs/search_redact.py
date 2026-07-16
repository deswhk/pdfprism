"""Search-and-redact dialog (PR 12.2).

Modal dialog that runs a full-document search, presents matches in
a checkbox list, and commits selected matches as pending redaction
annotations. See ARCHITECTURE.md for the two-phase mark-then-apply
model this shipping into.

The dialog is dumb: it knows how to search (via SearchService bound
in ``__init__``) and how to package selected hits, but the actual
commit-to-adapter goes through the caller (MainWindow) via the
``hits_selected`` signal on OK. Cancel returns nothing.

Case sensitivity and whole-word matching are exposed as toggles;
regex is deferred (see PR 12.2 Q4 discussion in the design note).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.types import SearchHit
from pdfprism.services.search import SearchService


class SearchRedactDialog(QDialog):
    """Search for a term across the document, redact selected matches."""

    # Emitted on OK with the list of user-selected hits.
    hits_selected = Signal(list)

    def __init__(
        self,
        adapter: PyMuPDFAdapter,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Search and Redact")
        self.setModal(True)
        self.resize(560, 480)

        self._adapter = adapter
        self._search_service = SearchService(adapter)
        self._hits: list[SearchHit] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ---- Search input row ----
        term_row = QHBoxLayout()
        term_row.addWidget(QLabel("Search term:"))
        self._term_input = QLineEdit()
        self._term_input.setPlaceholderText("e.g. John Smith, 123-45-6789")
        self._term_input.returnPressed.connect(self._run_search)
        term_row.addWidget(self._term_input)
        root.addLayout(term_row)

        # ---- Options + Search button ----
        opts_row = QHBoxLayout()
        self._case_sensitive = QCheckBox("Case sensitive")
        self._whole_word = QCheckBox("Whole word")
        opts_row.addWidget(self._case_sensitive)
        opts_row.addWidget(self._whole_word)
        opts_row.addStretch()
        self._search_button = QPushButton("Search")
        self._search_button.clicked.connect(self._run_search)
        opts_row.addWidget(self._search_button)
        root.addLayout(opts_row)

        # ---- Match count label ----
        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: gray;")
        root.addWidget(self._count_label)

        # ---- Results list ----
        self._results = QListWidget()
        self._results.itemChanged.connect(self._update_button_label)
        root.addWidget(self._results, 1)

        # ---- Select all / none ----
        sel_row = QHBoxLayout()
        self._select_all_button = QPushButton("Select All")
        self._select_all_button.clicked.connect(self._select_all)
        self._select_none_button = QPushButton("Select None")
        self._select_none_button.clicked.connect(self._select_none)
        sel_row.addWidget(self._select_all_button)
        sel_row.addWidget(self._select_none_button)
        sel_row.addStretch()
        root.addLayout(sel_row)

        # ---- OK / Cancel ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setText("Redact 0 Selected")
        self._ok_button.setEnabled(False)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ---- Slots ----

    def _run_search(self) -> None:
        term = self._term_input.text().strip()
        if not term:
            self._results.clear()
            self._count_label.setText("Enter a term to search.")
            self._hits = []
            self._update_button_label()
            return

        # Bind the service to the adapter for this run.
        hits = self._search_service.find_all(
            term,
            case_sensitive=self._case_sensitive.isChecked(),
            whole_word=self._whole_word.isChecked(),
        )
        self._hits = hits
        self._populate_results(term, hits)

    def _populate_results(self, term: str, hits: list[SearchHit]) -> None:
        self._results.clear()
        if not hits:
            self._count_label.setText(f'No matches for "{term}".')
            self._update_button_label()
            return
        self._count_label.setText(f"{len(hits)} match(es)")
        for hit in hits:
            label = f"Page {hit.page_index + 1}: {term}"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._results.addItem(item)
        self._update_button_label()

    def _select_all(self) -> None:
        for i in range(self._results.count()):
            self._results.item(i).setCheckState(Qt.CheckState.Checked)

    def _select_none(self) -> None:
        for i in range(self._results.count()):
            self._results.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _update_button_label(self, *args) -> None:
        n = self._checked_count()
        self._ok_button.setText(f"Redact {n} Selected")
        self._ok_button.setEnabled(n > 0)

    def _checked_count(self) -> int:
        return sum(
            1
            for i in range(self._results.count())
            if self._results.item(i).checkState() == Qt.CheckState.Checked
        )

    def _on_accept(self) -> None:
        selected: list[SearchHit] = []
        for i in range(self._results.count()):
            if self._results.item(i).checkState() == Qt.CheckState.Checked:
                selected.append(self._hits[i])
        self.hits_selected.emit(selected)
        self.accept()

    # ---- Public accessor (for callers that use exec() instead of signals) ----

    def selected_hits(self) -> list[SearchHit]:
        """Return the hits selected at OK time. Empty list on Cancel."""
        if self.result() != QDialog.DialogCode.Accepted:
            return []
        selected: list[SearchHit] = []
        for i in range(self._results.count()):
            if self._results.item(i).checkState() == Qt.CheckState.Checked:
                selected.append(self._hits[i])
        return selected

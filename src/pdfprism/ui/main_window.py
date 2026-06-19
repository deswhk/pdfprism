"""Main application window."""

import logging
from pathlib import Path

from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolBar,
)

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.exceptions import PdfPrismError
from pdfprism.ui.dialogs.goto_page import GotoPageDialog
from pdfprism.ui.widgets.page_view import PageView

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("pdfprism")
        self.resize(1100, 1100)

        self._adapter = PyMuPDFAdapter()
        self._page_view = PageView(self)
        self.setCentralWidget(self._page_view)

        self._page_view.page_changed.connect(self._on_page_changed)
        self._page_view.zoom_changed.connect(self._on_zoom_changed)

        # Status bar widgets
        self._page_indicator = QLabel("")
        self._zoom_indicator = QLabel("")
        self.statusBar().addPermanentWidget(self._page_indicator)
        self.statusBar().addPermanentWidget(self._zoom_indicator)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._update_status_bar()
        self._update_actions_enabled()

    # ----- actions, menus, toolbar -----

    def _build_actions(self) -> None:
        # File
        self.act_open = QAction("&Open...", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self._on_open)

        self.act_close_doc = QAction("&Close", self)
        self.act_close_doc.setShortcut(QKeySequence.StandardKey.Close)
        self.act_close_doc.triggered.connect(self._on_close_document)

        self.act_quit = QAction("&Quit", self)
        self.act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.act_quit.triggered.connect(self.close)

        # Navigation
        self.act_first_page = QAction("&First Page", self)
        self.act_first_page.setShortcut("Ctrl+Home")
        self.act_first_page.triggered.connect(self._page_view.first_page)

        self.act_prev_page = QAction("&Previous Page", self)
        self.act_prev_page.setShortcut("PgUp")
        self.act_prev_page.triggered.connect(self._page_view.prev_page)

        self.act_next_page = QAction("&Next Page", self)
        self.act_next_page.setShortcut("PgDown")
        self.act_next_page.triggered.connect(self._page_view.next_page)

        self.act_last_page = QAction("&Last Page", self)
        self.act_last_page.setShortcut("Ctrl+End")
        self.act_last_page.triggered.connect(self._page_view.last_page)

        self.act_goto_page = QAction("&Go to Page...", self)
        self.act_goto_page.setShortcut("Ctrl+G")
        self.act_goto_page.triggered.connect(self._on_goto_page)

        # View / Zoom
        self.act_fit_page = QAction("Fit &Page", self)
        self.act_fit_page.setShortcut("Ctrl+0")
        self.act_fit_page.triggered.connect(self._page_view.set_fit_page)

        self.act_fit_width = QAction("Fit &Width", self)
        self.act_fit_width.setShortcut("Ctrl+1")
        self.act_fit_width.triggered.connect(self._page_view.set_fit_width)

        self.act_actual_size = QAction("&Actual Size (100%)", self)
        self.act_actual_size.setShortcut("Ctrl+2")
        self.act_actual_size.triggered.connect(self._page_view.set_actual_size)

        self.act_zoom_in = QAction("Zoom &In", self)
        self.act_zoom_in.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        self.act_zoom_in.triggered.connect(self._page_view.zoom_in)

        self.act_zoom_out = QAction("Zoom &Out", self)
        self.act_zoom_out.setShortcut("Ctrl+-")
        self.act_zoom_out.triggered.connect(self._page_view.zoom_out)

    def _build_menus(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.act_open)
        file_menu.addAction(self.act_close_doc)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self.act_fit_page)
        view_menu.addAction(self.act_fit_width)
        view_menu.addAction(self.act_actual_size)
        view_menu.addSeparator()
        view_menu.addAction(self.act_zoom_in)
        view_menu.addAction(self.act_zoom_out)

        go_menu = menubar.addMenu("&Go")
        go_menu.addAction(self.act_first_page)
        go_menu.addAction(self.act_prev_page)
        go_menu.addAction(self.act_next_page)
        go_menu.addAction(self.act_last_page)
        go_menu.addSeparator()
        go_menu.addAction(self.act_goto_page)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addAction(self.act_first_page)
        toolbar.addAction(self.act_prev_page)
        toolbar.addAction(self.act_next_page)
        toolbar.addAction(self.act_last_page)
        toolbar.addSeparator()
        toolbar.addAction(self.act_fit_page)
        toolbar.addAction(self.act_fit_width)
        toolbar.addAction(self.act_actual_size)
        toolbar.addSeparator()
        toolbar.addAction(self.act_zoom_in)
        toolbar.addAction(self.act_zoom_out)

    # ----- slots -----

    def _on_open(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", "", "PDF files (*.pdf);;All files (*)"
        )
        if not path_str:
            return
        try:
            self._adapter.open(Path(path_str))
        except PdfPrismError as exc:
            logger.exception("Failed to open %s", path_str)
            QMessageBox.critical(self, "Open failed", str(exc))
            return

        self._page_view.set_adapter(self._adapter)
        self.setWindowTitle(f"pdfprism - {Path(path_str).name}")
        self._update_actions_enabled()

    def _on_close_document(self) -> None:
        self._page_view.clear()
        self._adapter.close()
        self.setWindowTitle("pdfprism")
        self._update_status_bar()
        self._update_actions_enabled()

    def _on_goto_page(self) -> None:
        page_count = self._page_view.page_count
        if page_count == 0:
            return
        current_1based = self._page_view.current_page + 1
        dialog = GotoPageDialog(current_1based, page_count, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._page_view.go_to_page(dialog.page_number - 1)

    def _on_page_changed(self, index: int) -> None:
        self._update_status_bar()
        self._update_actions_enabled()

    def _on_zoom_changed(self, ratio: float) -> None:
        self._update_status_bar()

    # ----- helpers -----

    def _update_status_bar(self) -> None:
        page_count = self._page_view.page_count
        if page_count == 0:
            self._page_indicator.setText("")
            self._zoom_indicator.setText("")
            return
        current_1based = self._page_view.current_page + 1
        self._page_indicator.setText(f"Page {current_1based} of {page_count}")
        zoom = self._page_view.effective_zoom
        self._zoom_indicator.setText(f"{int(round(zoom * 100))}%")

    def _update_actions_enabled(self) -> None:
        has_doc = self._page_view.page_count > 0
        current = self._page_view.current_page
        page_count = self._page_view.page_count

        self.act_close_doc.setEnabled(has_doc)
        self.act_goto_page.setEnabled(has_doc)
        self.act_fit_page.setEnabled(has_doc)
        self.act_fit_width.setEnabled(has_doc)
        self.act_actual_size.setEnabled(has_doc)
        self.act_zoom_in.setEnabled(has_doc)
        self.act_zoom_out.setEnabled(has_doc)

        self.act_first_page.setEnabled(has_doc and current > 0)
        self.act_prev_page.setEnabled(has_doc and current > 0)
        self.act_next_page.setEnabled(has_doc and current < page_count - 1)
        self.act_last_page.setEnabled(has_doc and current < page_count - 1)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        try:
            self._adapter.close()
        finally:
            super().closeEvent(event)

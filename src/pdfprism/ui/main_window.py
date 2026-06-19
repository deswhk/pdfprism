"""Main application window.

PR 1 minimum: open a PDF via the File menu and render page 1 to a QLabel.
Real page navigation, zoom, and view modes land in PR 2.
"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
)

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.exceptions import PdfPrismError

logger = logging.getLogger(__name__)

_PLACEHOLDER_TEXT = "Open a PDF via File > Open (Ctrl+O)"
_PLACEHOLDER_STYLE = "color: #888; padding: 24px;"


class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("pdfprism")
        self.resize(900, 1100)

        self._adapter = PyMuPDFAdapter()
        self._page_label = QLabel(_PLACEHOLDER_TEXT)
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setStyleSheet(_PLACEHOLDER_STYLE)

        scroll = QScrollArea()
        scroll.setWidget(self._page_label)
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(scroll)

        self._build_menus()

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        open_action = QAction("&Open...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open)
        file_menu.addAction(open_action)

        close_action = QAction("&Close", self)
        close_action.setShortcut("Ctrl+W")
        close_action.triggered.connect(self._on_close_document)
        file_menu.addAction(close_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _on_open(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Open PDF",
            "",
            "PDF files (*.pdf);;All files (*)",
        )
        if not path_str:
            return
        try:
            self._adapter.open(Path(path_str))
        except PdfPrismError as exc:
            logger.exception("Failed to open %s", path_str)
            QMessageBox.critical(self, "Open failed", str(exc))
            return

        self._render_first_page()
        self.setWindowTitle(f"pdfprism - {Path(path_str).name}")

    def _on_close_document(self) -> None:
        self._adapter.close()
        self._page_label.clear()
        self._page_label.setText(_PLACEHOLDER_TEXT)
        self._page_label.setStyleSheet(_PLACEHOLDER_STYLE)
        self.setWindowTitle("pdfprism")

    def _render_first_page(self) -> None:
        png_bytes = self._adapter.render_page(0, zoom=1.5)
        pixmap = QPixmap()
        pixmap.loadFromData(png_bytes, "PNG")
        self._page_label.setPixmap(pixmap)
        self._page_label.setStyleSheet("")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        try:
            self._adapter.close()
        finally:
            super().closeEvent(event)

"""Main application window."""

import logging
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QToolBar,
    QWidget,
)

from pdfprism.config import MAX_RECENT_FILES
from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.exceptions import PdfPrismError
from pdfprism.core.types import SearchHit
from pdfprism.services.search import SearchService
from pdfprism.ui.dialogs.goto_page import GotoPageDialog
from pdfprism.ui.page_cache import PageCache
from pdfprism.ui.theme import DARK_QSS
from pdfprism.ui.widgets.outline_panel import OutlinePanel
from pdfprism.ui.widgets.page_view import PageView, ViewMode
from pdfprism.ui.widgets.search_bar import SearchBar
from pdfprism.ui.widgets.thumbnail_panel import ThumbnailPanel

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("pdfprism")
        self.resize(1300, 1100)

        self._adapter = PyMuPDFAdapter()
        self._recent_menu: QMenu | None = None
        self._page_cache = PageCache()
        self._search_service = SearchService(self._adapter)
        self._fullscreen_state: dict[str, bool] | None = None
        settings = QSettings()
        self._dark_mode: bool = settings.value("view/dark_mode", False, type=bool)

        # Search cursor state (MainWindow owns this; PageView and SearchBar
        # are told what to display).
        self._search_hits: list[SearchHit] = []
        self._current_hit_index: int = -1

        self._page_view = PageView(self._page_cache, self)
        self.setCentralWidget(self._page_view)

        # Sidebars
        self._thumbnail_panel = ThumbnailPanel(self._page_cache, self)
        self._outline_panel = OutlinePanel(self)
        self._thumbnail_dock = self._make_dock("Thumbnails", self._thumbnail_panel)
        self._outline_dock = self._make_dock("Outline", self._outline_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._thumbnail_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._outline_dock)
        self.tabifyDockWidget(self._thumbnail_dock, self._outline_dock)
        self._thumbnail_dock.raise_()

        # Search bar in its own toolbar (hidden until Ctrl+F)
        self._search_bar = SearchBar(self)
        self._search_toolbar = QToolBar("Find", self)
        self._search_toolbar.setMovable(False)
        self._search_toolbar.addWidget(self._search_bar)
        self._search_toolbar.setVisible(False)

        # Signal wiring
        self._page_view.page_changed.connect(self._on_page_changed)
        self._page_view.zoom_changed.connect(self._on_zoom_changed)
        self._page_view.view_mode_changed.connect(self._on_view_mode_changed)
        self._page_view.page_changed.connect(self._thumbnail_panel.set_current_page)
        self._thumbnail_panel.page_selected.connect(self._page_view.go_to_page)
        self._outline_panel.page_selected.connect(self._page_view.go_to_page)

        self._search_bar.find_requested.connect(self._on_find)
        self._search_bar.next_requested.connect(self._on_find_next)
        self._search_bar.prev_requested.connect(self._on_find_prev)
        self._search_bar.closed.connect(self._on_close_search)

        # Status bar widgets
        self._page_indicator = QLabel("")
        self._zoom_indicator = QLabel("")
        self.statusBar().addPermanentWidget(self._page_indicator)
        self.statusBar().addPermanentWidget(self._zoom_indicator)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        # Search toolbar goes below the main toolbar.
        self.addToolBarBreak()
        self.addToolBar(self._search_toolbar)

        self.act_toggle_dark_mode.setChecked(self._dark_mode)
        self._apply_theme()

        self._update_recent_menu()

        self._update_status_bar()
        self._update_actions_enabled()

    @staticmethod
    def _make_dock(title: str, widget: QWidget) -> QDockWidget:
        dock = QDockWidget(title)
        dock.setWidget(widget)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        return dock

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

        # Edit (Find)
        self.act_find = QAction("&Find...", self)
        self.act_find.setShortcut(QKeySequence.StandardKey.Find)
        self.act_find.triggered.connect(self._on_open_search)

        self.act_find_next = QAction("Find &Next", self)
        self.act_find_next.setShortcut(QKeySequence.StandardKey.FindNext)
        self.act_find_next.triggered.connect(self._on_find_next)

        self.act_find_prev = QAction("Find &Previous", self)
        self.act_find_prev.setShortcut(QKeySequence.StandardKey.FindPrevious)
        self.act_find_prev.triggered.connect(self._on_find_prev)

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

        # View modes
        self.act_single_page = QAction("&Single Page", self)
        self.act_single_page.setCheckable(True)
        self.act_single_page.setShortcut("Ctrl+3")
        self.act_single_page.triggered.connect(
            lambda: self._page_view.set_view_mode(ViewMode.SINGLE_PAGE)
        )

        self.act_continuous = QAction("&Continuous", self)
        self.act_continuous.setCheckable(True)
        self.act_continuous.setShortcut("Ctrl+4")
        self.act_continuous.triggered.connect(
            lambda: self._page_view.set_view_mode(ViewMode.CONTINUOUS)
        )

        self.view_mode_group = QActionGroup(self)
        self.view_mode_group.addAction(self.act_single_page)
        self.view_mode_group.addAction(self.act_continuous)
        self.view_mode_group.setExclusive(True)
        self.act_single_page.setChecked(True)

        self.act_fullscreen = QAction("&Full Screen", self)
        self.act_fullscreen.setShortcut("F11")
        self.act_fullscreen.setCheckable(True)
        self.act_fullscreen.triggered.connect(self._on_toggle_fullscreen)

        self.act_toggle_dark_mode = QAction("&Dark Mode", self)
        self.act_toggle_dark_mode.setCheckable(True)
        self.act_toggle_dark_mode.triggered.connect(self._on_toggle_dark_mode)

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

        # Dock toggles
        self.act_toggle_thumbnails = self._thumbnail_dock.toggleViewAction()
        self.act_toggle_thumbnails.setText("&Thumbnails")
        self.act_toggle_thumbnails.setShortcut("F4")

        self.act_toggle_outline = self._outline_dock.toggleViewAction()
        self.act_toggle_outline.setText("&Outline")
        self.act_toggle_outline.setShortcut("F5")

        # Register all actions on the main window so their shortcuts remain
        # active when menus and toolbars are hidden (e.g., in full-screen).
        for action in [
            self.act_open,
            self.act_close_doc,
            self.act_quit,
            self.act_find,
            self.act_find_next,
            self.act_find_prev,
            self.act_first_page,
            self.act_prev_page,
            self.act_next_page,
            self.act_last_page,
            self.act_goto_page,
            self.act_single_page,
            self.act_continuous,
            self.act_fullscreen,
            self.act_toggle_dark_mode,
            self.act_fit_page,
            self.act_fit_width,
            self.act_actual_size,
            self.act_zoom_in,
            self.act_zoom_out,
            self.act_toggle_thumbnails,
            self.act_toggle_outline,
        ]:
            self.addAction(action)

    def _build_menus(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.act_open)
        self._recent_menu = file_menu.addMenu("Open &Recent")
        file_menu.addAction(self.act_close_doc)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(self.act_find)
        edit_menu.addAction(self.act_find_next)
        edit_menu.addAction(self.act_find_prev)

        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self.act_single_page)
        view_menu.addAction(self.act_continuous)
        view_menu.addSeparator()
        view_menu.addAction(self.act_fit_page)
        view_menu.addAction(self.act_fit_width)
        view_menu.addAction(self.act_actual_size)
        view_menu.addSeparator()
        view_menu.addAction(self.act_zoom_in)
        view_menu.addAction(self.act_zoom_out)
        view_menu.addSeparator()
        view_menu.addAction(self.act_toggle_thumbnails)
        view_menu.addAction(self.act_toggle_outline)
        view_menu.addSeparator()
        view_menu.addAction(self.act_fullscreen)
        view_menu.addAction(self.act_toggle_dark_mode)

        go_menu = menubar.addMenu("&Go")
        go_menu.addAction(self.act_first_page)
        go_menu.addAction(self.act_prev_page)
        go_menu.addAction(self.act_next_page)
        go_menu.addAction(self.act_last_page)
        go_menu.addSeparator()
        go_menu.addAction(self.act_goto_page)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        self._main_toolbar = toolbar
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

    # ----- file slots -----

    def _on_open(self) -> None:
        settings = QSettings()
        last_dir = settings.value("recent/last_dir", "", type=str)
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", last_dir, "PDF files (*.pdf);;All files (*)"
        )
        if not path_str:
            return
        settings.setValue("recent/last_dir", str(Path(path_str).parent))
        self._open_path(Path(path_str))

    def _open_path(self, path: Path) -> None:
        try:
            path = path.resolve(strict=False)
        except OSError:
            pass
        try:
            self._adapter.open(path)
        except PdfPrismError as exc:
            logger.exception("Failed to open %s", path)
            QMessageBox.critical(self, "Open failed", str(exc))
            # Adapter has already closed any previous document; sync UI.
            self._reset_to_empty_state()
            return

        self._reset_search_state()
        self._page_view.set_adapter(self._adapter)
        self._thumbnail_panel.set_adapter(self._adapter)
        self._outline_panel.set_outline(self._adapter.get_outline())
        self.setWindowTitle(f"pdfprism - {path.name}")
        self._update_actions_enabled()
        self._add_recent_file(path)

    def _on_close_document(self) -> None:
        self._reset_to_empty_state()
        self._adapter.close()

    def _reset_to_empty_state(self) -> None:
        """Reset all UI to no-doc state. Does not touch the adapter."""
        self._reset_search_state()
        self._page_view.clear()
        self._thumbnail_panel.set_adapter(None)
        self._outline_panel.set_outline([])
        self.setWindowTitle("pdfprism")
        self._update_status_bar()
        self._update_actions_enabled()

    # ----- navigation slot -----

    def _on_goto_page(self) -> None:
        page_count = self._page_view.page_count
        if page_count == 0:
            return
        current_1based = self._page_view.current_page + 1
        dialog = GotoPageDialog(current_1based, page_count, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._page_view.go_to_page(dialog.page_number - 1)

    # ----- search slots -----

    def _on_open_search(self) -> None:
        self._search_toolbar.setVisible(True)
        self._search_bar.focus_input()

    def _on_close_search(self) -> None:
        self._reset_search_state()
        self._search_toolbar.setVisible(False)

    def _on_find(self, term: str) -> None:
        if self._page_view.page_count == 0:
            return
        hits = self._search_service.find_all(term)
        self._search_hits = hits
        self._page_view.set_search_hits(hits)
        if hits:
            self._current_hit_index = 0
            self._update_current_hit()
        else:
            self._current_hit_index = -1
            self._search_bar.set_match_count(0, 0)

    def _on_find_next(self) -> None:
        if not self._search_hits:
            return
        self._current_hit_index = (self._current_hit_index + 1) % len(self._search_hits)
        self._update_current_hit()

    def _on_find_prev(self) -> None:
        if not self._search_hits:
            return
        self._current_hit_index = (self._current_hit_index - 1) % len(self._search_hits)
        self._update_current_hit()

    def _update_current_hit(self) -> None:
        hit = self._search_hits[self._current_hit_index]
        self._page_view.set_current_hit(hit)
        self._search_bar.set_match_count(self._current_hit_index + 1, len(self._search_hits))

    def _reset_search_state(self) -> None:
        self._search_hits = []
        self._current_hit_index = -1
        self._page_view.clear_search()
        self._search_bar.clear()

    # ----- view-state slots -----

    def _on_page_changed(self, index: int) -> None:
        self._update_status_bar()
        self._update_actions_enabled()

    def _on_zoom_changed(self, _ratio: float) -> None:
        self._update_status_bar()

    def _on_view_mode_changed(self, mode: ViewMode) -> None:
        if mode == ViewMode.SINGLE_PAGE:
            self.act_single_page.setChecked(True)
        else:
            self.act_continuous.setChecked(True)

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

        self.act_find.setEnabled(has_doc)
        self.act_find_next.setEnabled(has_doc)
        self.act_find_prev.setEnabled(has_doc)

        self.act_first_page.setEnabled(has_doc and current > 0)
        self.act_prev_page.setEnabled(has_doc and current > 0)
        self.act_next_page.setEnabled(has_doc and current < page_count - 1)
        self.act_last_page.setEnabled(has_doc and current < page_count - 1)

    def _on_toggle_fullscreen(self) -> None:
        if self._fullscreen_state is None:
            self._fullscreen_state = {
                "menubar": self.menuBar().isVisible(),
                "main_toolbar": self._main_toolbar.isVisible(),
                "search_toolbar": self._search_toolbar.isVisible(),
                "statusbar": self.statusBar().isVisible(),
                "thumbnail_dock": self._thumbnail_dock.isVisible(),
                "outline_dock": self._outline_dock.isVisible(),
            }
            self.menuBar().setVisible(False)
            self._main_toolbar.setVisible(False)
            self._search_toolbar.setVisible(False)
            self.statusBar().setVisible(False)
            self._thumbnail_dock.setVisible(False)
            self._outline_dock.setVisible(False)
            self.showFullScreen()
            self.act_fullscreen.setChecked(True)
        else:
            state = self._fullscreen_state
            self.menuBar().setVisible(state["menubar"])
            self._main_toolbar.setVisible(state["main_toolbar"])
            self._search_toolbar.setVisible(state["search_toolbar"])
            self.statusBar().setVisible(state["statusbar"])
            self._thumbnail_dock.setVisible(state["thumbnail_dock"])
            self._outline_dock.setVisible(state["outline_dock"])
            self._fullscreen_state = None
            self.showNormal()
            self.act_fullscreen.setChecked(False)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._fullscreen_state is not None:
            self._on_toggle_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_toggle_dark_mode(self, checked: bool) -> None:
        self._dark_mode = checked
        self._apply_theme()
        settings = QSettings()
        settings.setValue("view/dark_mode", checked)

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(DARK_QSS if self._dark_mode else "")

    def _load_recent_files(self) -> list[Path]:
        settings = QSettings()
        joined = settings.value("recent/files", "", type=str)
        if not joined:
            return []
        return [Path(p) for p in joined.split("\n") if p]

    def _save_recent_files(self, paths: list[Path]) -> None:
        settings = QSettings()
        settings.setValue("recent/files", "\n".join(str(p) for p in paths))

    def _add_recent_file(self, path: Path) -> None:
        paths = [p for p in self._load_recent_files() if p != path]
        paths.insert(0, path)
        paths = paths[:MAX_RECENT_FILES]
        self._save_recent_files(paths)
        self._update_recent_menu()

    def _clear_recent_files(self) -> None:
        self._save_recent_files([])
        self._update_recent_menu()

    def _update_recent_menu(self) -> None:
        if self._recent_menu is None:
            return
        self._recent_menu.clear()
        existing = [p for p in self._load_recent_files() if p.exists()]
        if not existing:
            empty = QAction("(No recent files)", self._recent_menu)
            empty.setEnabled(False)
            self._recent_menu.addAction(empty)
            return
        for p in existing:
            action = QAction(p.name, self._recent_menu)
            action.setToolTip(str(p))
            action.triggered.connect(lambda checked=False, path=p: self._open_path(path))
            self._recent_menu.addAction(action)
        self._recent_menu.addSeparator()
        clear_action = QAction("Clear Recent", self._recent_menu)
        clear_action.triggered.connect(self._clear_recent_files)
        self._recent_menu.addAction(clear_action)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        try:
            self._adapter.close()
        finally:
            super().closeEvent(event)

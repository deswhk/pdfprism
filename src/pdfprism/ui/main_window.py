"""Main application window with multi-document tabs."""

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
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QWidget,
)

from pdfprism.config import MAX_RECENT_FILES
from pdfprism.core.exceptions import PdfPrismError
from pdfprism.core.types import CrossDocHit
from pdfprism.services.search import SearchScope, SearchService
from pdfprism.ui.dialogs.goto_page import GotoPageDialog
from pdfprism.ui.theme import DARK_QSS
from pdfprism.ui.widgets.document_view import DocumentView
from pdfprism.ui.widgets.page_view import ViewMode
from pdfprism.ui.widgets.search_bar import SearchBar
from pdfprism.ui.widgets.search_results_panel import SearchResultsPanel

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Top-level window with tabbed multi-document support.

    Per-document state (adapter, page cache, page view, sidebars, search
    cursor) lives inside DocumentView. MainWindow holds the chrome and
    coordinates tab management plus global UI state (full-screen, dark
    mode, recent files, last-directory memory, cross-document search).
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("pdfprism")
        self.resize(1300, 1100)

        settings = QSettings()
        self._fullscreen_state: dict[str, bool] | None = None
        self._dark_mode: bool = settings.value("view/dark_mode", False, type=bool)
        self._recent_menu: QMenu | None = None
        self._main_toolbar: QToolBar | None = None
        self._active_tab: DocumentView | None = None

        # Cross-document search state. Populated by _on_find_all_open;
        # walked by _on_find_next / _on_find_prev when scope is ALL_OPEN.
        self._cross_search_results: list[CrossDocHit] = []
        self._cross_search_index: int = -1

        # Central widget: stacked placeholder + tab widget.
        self._stacked_central = QStackedWidget(self)
        self.setCentralWidget(self._stacked_central)

        self._empty_placeholder = QLabel(
            "Open a PDF (Ctrl+O) or pick one from File \u2192 Open Recent"
        )
        self._empty_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_placeholder.setStyleSheet("color: gray; font-size: 14pt; padding: 40px;")

        self._tab_widget = QTabWidget(self)
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.setMovable(True)
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.tabCloseRequested.connect(self._on_tab_close_requested)
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

        self._stacked_central.addWidget(self._empty_placeholder)  # index 0
        self._stacked_central.addWidget(self._tab_widget)  # index 1
        self._stacked_central.setCurrentIndex(0)

        # Sidebar docks (left): per-tab thumbnail/outline panels in stacks.
        self._thumbnail_stack = QStackedWidget(self)
        self._thumbnail_stack.addWidget(QWidget(self))
        self._outline_stack = QStackedWidget(self)
        self._outline_stack.addWidget(QWidget(self))

        self._thumbnail_dock = self._make_dock("Thumbnails", self._thumbnail_stack)
        self._outline_dock = self._make_dock("Outline", self._outline_stack)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._thumbnail_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._outline_dock)
        self.tabifyDockWidget(self._thumbnail_dock, self._outline_dock)
        self._thumbnail_dock.raise_()

        # Cross-search results dock (right); auto-shown on cross-search,
        # auto-hidden on close-search or when a single-doc search runs.
        self._results_panel = SearchResultsPanel(self)
        self._results_dock = self._make_dock("Search Results", self._results_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._results_dock)
        self._results_dock.setVisible(False)
        self._results_panel.result_selected.connect(self._on_result_selected)

        # Search bar in its own toolbar (hidden until Ctrl+F).
        self._search_bar = SearchBar(self)
        self._search_toolbar = QToolBar("Find", self)
        self._search_toolbar.setMovable(False)
        self._search_toolbar.addWidget(self._search_bar)
        self._search_toolbar.setVisible(False)

        self._search_bar.find_requested.connect(self._on_find)
        self._search_bar.next_requested.connect(self._on_find_next)
        self._search_bar.prev_requested.connect(self._on_find_prev)
        self._search_bar.closed.connect(self._on_close_search)

        # Status bar widgets.
        self._page_indicator = QLabel("")
        self._zoom_indicator = QLabel("")
        self.statusBar().addPermanentWidget(self._page_indicator)
        self.statusBar().addPermanentWidget(self._zoom_indicator)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
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
        self.act_open = QAction("&Open...", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self._on_open)

        self.act_close_doc = QAction("&Close Tab", self)
        self.act_close_doc.setShortcut(QKeySequence.StandardKey.Close)
        self.act_close_doc.triggered.connect(self._on_close_tab)

        self.act_quit = QAction("&Quit", self)
        self.act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.act_quit.triggered.connect(self.close)

        self.act_find = QAction("&Find...", self)
        self.act_find.setShortcut(QKeySequence.StandardKey.Find)
        self.act_find.triggered.connect(self._on_open_search)

        self.act_find_next = QAction("Find &Next", self)
        self.act_find_next.setShortcut(QKeySequence.StandardKey.FindNext)
        self.act_find_next.triggered.connect(self._on_find_next)

        self.act_find_prev = QAction("Find &Previous", self)
        self.act_find_prev.setShortcut(QKeySequence.StandardKey.FindPrevious)
        self.act_find_prev.triggered.connect(self._on_find_prev)

        self.act_first_page = QAction("&First Page", self)
        self.act_first_page.setShortcut("Ctrl+Home")
        self.act_first_page.triggered.connect(self._nav_first)

        self.act_prev_page = QAction("&Previous Page", self)
        self.act_prev_page.setShortcut("PgUp")
        self.act_prev_page.triggered.connect(self._nav_prev)

        self.act_next_page = QAction("&Next Page", self)
        self.act_next_page.setShortcut("PgDown")
        self.act_next_page.triggered.connect(self._nav_next)

        self.act_last_page = QAction("&Last Page", self)
        self.act_last_page.setShortcut("Ctrl+End")
        self.act_last_page.triggered.connect(self._nav_last)

        self.act_goto_page = QAction("&Go to Page...", self)
        self.act_goto_page.setShortcut("Ctrl+G")
        self.act_goto_page.triggered.connect(self._on_goto_page)

        self.act_next_tab = QAction("Next Tab", self)
        self.act_next_tab.setShortcut("Ctrl+PgDown")
        self.act_next_tab.triggered.connect(self._on_next_tab)

        self.act_prev_tab = QAction("Previous Tab", self)
        self.act_prev_tab.setShortcut("Ctrl+PgUp")
        self.act_prev_tab.triggered.connect(self._on_prev_tab)

        self.act_single_page = QAction("&Single Page", self)
        self.act_single_page.setCheckable(True)
        self.act_single_page.setShortcut("Ctrl+3")
        self.act_single_page.triggered.connect(
            lambda: self._set_active_view_mode(ViewMode.SINGLE_PAGE)
        )

        self.act_continuous = QAction("&Continuous", self)
        self.act_continuous.setCheckable(True)
        self.act_continuous.setShortcut("Ctrl+4")
        self.act_continuous.triggered.connect(
            lambda: self._set_active_view_mode(ViewMode.CONTINUOUS)
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

        self.act_fit_page = QAction("Fit &Page", self)
        self.act_fit_page.setShortcut("Ctrl+0")
        self.act_fit_page.triggered.connect(self._on_fit_page)

        self.act_fit_width = QAction("Fit &Width", self)
        self.act_fit_width.setShortcut("Ctrl+1")
        self.act_fit_width.triggered.connect(self._on_fit_width)

        self.act_actual_size = QAction("&Actual Size (100%)", self)
        self.act_actual_size.setShortcut("Ctrl+2")
        self.act_actual_size.triggered.connect(self._on_actual_size)

        self.act_zoom_in = QAction("Zoom &In", self)
        self.act_zoom_in.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        self.act_zoom_in.triggered.connect(self._on_zoom_in)

        self.act_zoom_out = QAction("Zoom &Out", self)
        self.act_zoom_out.setShortcut("Ctrl+-")
        self.act_zoom_out.triggered.connect(self._on_zoom_out)

        self.act_toggle_thumbnails = self._thumbnail_dock.toggleViewAction()
        self.act_toggle_thumbnails.setText("&Thumbnails")
        self.act_toggle_thumbnails.setShortcut("F4")

        self.act_toggle_outline = self._outline_dock.toggleViewAction()
        self.act_toggle_outline.setText("&Outline")
        self.act_toggle_outline.setShortcut("F5")

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
            self.act_next_tab,
            self.act_prev_tab,
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
        go_menu.addSeparator()
        go_menu.addAction(self.act_prev_tab)
        go_menu.addAction(self.act_next_tab)

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

    # ----- tab management -----

    def _add_tab(self, doc_view: DocumentView) -> int:
        """Add a DocumentView as a new tab; return the new tab index."""
        # Add sidebar panels to their stacks BEFORE addTab, because
        # addTab fires currentChanged synchronously when this is the
        # first tab. _on_tab_changed runs from that signal and needs
        # to find the panels already in the stacks to make them current.
        self._thumbnail_stack.addWidget(doc_view.thumbnail_panel)
        self._outline_stack.addWidget(doc_view.outline_panel)
        tab_idx = self._tab_widget.addTab(doc_view, doc_view.path.name)
        self._tab_widget.setTabToolTip(tab_idx, str(doc_view.path))
        return tab_idx

    def _on_tab_close_requested(self, index: int) -> None:
        doc_view = self._tab_widget.widget(index)
        if not isinstance(doc_view, DocumentView):
            return
        # Cross-search results index tabs by position; removing a tab
        # invalidates those indices, so drop the result set rather than
        # try to remap.
        if self._cross_search_results:
            self._clear_cross_search()
        self._thumbnail_stack.removeWidget(doc_view.thumbnail_panel)
        self._outline_stack.removeWidget(doc_view.outline_panel)
        self._tab_widget.removeTab(index)
        doc_view.close_document()
        doc_view.thumbnail_panel.deleteLater()
        doc_view.outline_panel.deleteLater()
        doc_view.deleteLater()
        if self._tab_widget.count() == 0:
            self._enter_empty_state()

    def _on_tab_changed(self, index: int) -> None:
        if self._active_tab is not None:
            try:
                self._active_tab.page_changed.disconnect(self._on_page_changed)
                self._active_tab.zoom_changed.disconnect(self._on_zoom_changed)
                self._active_tab.view_mode_changed.disconnect(self._on_view_mode_changed)
            except (RuntimeError, TypeError):
                pass

        if index < 0 or self._tab_widget.count() == 0:
            self._enter_empty_state()
            return

        doc_view = self._tab_widget.widget(index)
        if not isinstance(doc_view, DocumentView):
            return

        self._active_tab = doc_view
        self._stacked_central.setCurrentIndex(1)
        thumb_idx = self._thumbnail_stack.indexOf(doc_view.thumbnail_panel)
        if thumb_idx >= 0:
            self._thumbnail_stack.setCurrentIndex(thumb_idx)
        outline_idx = self._outline_stack.indexOf(doc_view.outline_panel)
        if outline_idx >= 0:
            self._outline_stack.setCurrentIndex(outline_idx)

        doc_view.page_changed.connect(self._on_page_changed)
        doc_view.zoom_changed.connect(self._on_zoom_changed)
        doc_view.view_mode_changed.connect(self._on_view_mode_changed)

        mode = doc_view.page_view.view_mode
        if mode == ViewMode.SINGLE_PAGE:
            self.act_single_page.setChecked(True)
        else:
            self.act_continuous.setChecked(True)
        self.setWindowTitle(f"pdfprism - {doc_view.path.name}")
        self._update_status_bar()
        self._update_actions_enabled()
        # Closing the search toolbar on tab switch is right for single-doc
        # search (each tab has its own state). For cross-search the result
        # set spans tabs, so skip the close when cross-search is active --
        # otherwise navigating across doc boundaries via _jump_to_cross_hit
        # would drop the result set mid-walk.
        if self._search_toolbar.isVisible() and not self._cross_search_results:
            self._on_close_search()

    def _enter_empty_state(self) -> None:
        self._active_tab = None
        self._stacked_central.setCurrentIndex(0)
        self._thumbnail_stack.setCurrentIndex(0)
        self._outline_stack.setCurrentIndex(0)
        self.setWindowTitle("pdfprism")
        if self._search_toolbar.isVisible():
            self._on_close_search()
        self._clear_cross_search()
        self._update_status_bar()
        self._update_actions_enabled()

    def _on_next_tab(self) -> None:
        if self._tab_widget.count() <= 1:
            return
        new_idx = (self._tab_widget.currentIndex() + 1) % self._tab_widget.count()
        self._tab_widget.setCurrentIndex(new_idx)

    def _on_prev_tab(self) -> None:
        if self._tab_widget.count() <= 1:
            return
        new_idx = (self._tab_widget.currentIndex() - 1) % self._tab_widget.count()
        self._tab_widget.setCurrentIndex(new_idx)

    def _on_close_tab(self) -> None:
        idx = self._tab_widget.currentIndex()
        if idx >= 0:
            self._on_tab_close_requested(idx)

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

        doc_view = DocumentView(path, self)
        try:
            doc_view.open()
        except PdfPrismError as exc:
            logger.exception("Failed to open %s", path)
            doc_view.deleteLater()
            QMessageBox.critical(self, "Open failed", str(exc))
            return

        tab_idx = self._add_tab(doc_view)
        self._tab_widget.setCurrentIndex(tab_idx)
        self._add_recent_file(path)

    # ----- navigation slots -----

    def _nav_first(self) -> None:
        if self._active_tab is not None:
            self._active_tab.page_view.first_page()

    def _nav_prev(self) -> None:
        if self._active_tab is not None:
            self._active_tab.page_view.prev_page()

    def _nav_next(self) -> None:
        if self._active_tab is not None:
            self._active_tab.page_view.next_page()

    def _nav_last(self) -> None:
        if self._active_tab is not None:
            self._active_tab.page_view.last_page()

    def _on_goto_page(self) -> None:
        if self._active_tab is None:
            return
        page_count = self._active_tab.page_view.page_count
        if page_count == 0:
            return
        current_1based = self._active_tab.page_view.current_page + 1
        dialog = GotoPageDialog(current_1based, page_count, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._active_tab.page_view.go_to_page(dialog.page_number - 1)

    # ----- zoom + view-mode slots -----

    def _on_fit_page(self) -> None:
        if self._active_tab is not None:
            self._active_tab.page_view.set_fit_page()

    def _on_fit_width(self) -> None:
        if self._active_tab is not None:
            self._active_tab.page_view.set_fit_width()

    def _on_actual_size(self) -> None:
        if self._active_tab is not None:
            self._active_tab.page_view.set_actual_size()

    def _on_zoom_in(self) -> None:
        if self._active_tab is not None:
            self._active_tab.page_view.zoom_in()

    def _on_zoom_out(self) -> None:
        if self._active_tab is not None:
            self._active_tab.page_view.zoom_out()

    def _set_active_view_mode(self, mode: ViewMode) -> None:
        if self._active_tab is not None:
            self._active_tab.page_view.set_view_mode(mode)

    # ----- search slots -----

    def _on_open_search(self) -> None:
        if self._active_tab is None:
            return
        self._search_toolbar.setVisible(True)
        self._search_bar.focus_input()

    def _on_close_search(self) -> None:
        if self._active_tab is not None:
            self._reset_search_state(self._active_tab)
        self._clear_cross_search()
        self._search_toolbar.setVisible(False)

    def _on_find(self, term: str) -> None:
        if self._search_bar.search_scope == SearchScope.ALL_OPEN:
            self._on_find_all_open(term)
            return
        # Single-doc search: any prior cross-search results no longer apply.
        self._clear_cross_search()
        if self._active_tab is None:
            return
        if self._active_tab.page_view.page_count == 0:
            return
        hits = self._active_tab.search_service.find_all(
            term,
            case_sensitive=self._search_bar.case_sensitive,
            whole_word=self._search_bar.whole_word,
        )
        self._active_tab.search_hits = hits
        self._active_tab.page_view.set_search_hits(hits)
        if hits:
            self._active_tab.current_hit_index = 0
            self._update_current_hit()
        else:
            self._active_tab.current_hit_index = -1
            self._search_bar.set_match_count(0, 0)

    def _on_find_all_open(self, term: str) -> None:
        """Search every open tab; populate the results dock and jump to hit 0."""
        adapters = []
        titles = []
        for i in range(self._tab_widget.count()):
            tab = self._tab_widget.widget(i)
            if isinstance(tab, DocumentView):
                adapters.append(tab.adapter)
                titles.append(tab.path.name)
        results = SearchService.find_all_across(
            adapters,
            term,
            case_sensitive=self._search_bar.case_sensitive,
            whole_word=self._search_bar.whole_word,
        )
        self._cross_search_results = results
        self._results_panel.set_results(results, titles)
        docs_with_hits = len({r.doc_index for r in results})
        if results:
            self._results_dock.setVisible(True)
            self._cross_search_index = 0
            self._jump_to_cross_hit(0)
        else:
            self._cross_search_index = -1
            self._results_dock.setVisible(True)
            self._search_bar.set_aggregate_count(0, 0)
        logger.info(
            "Cross-search %r: %d hits in %d documents",
            term,
            len(results),
            docs_with_hits,
        )

    def _jump_to_cross_hit(self, index: int) -> None:
        """Switch to the tab owning ``cross_search_results[index]`` and highlight it."""
        if not (0 <= index < len(self._cross_search_results)):
            return
        self._cross_search_index = index
        cross_hit = self._cross_search_results[index]
        target_tab = self._tab_widget.widget(cross_hit.doc_index)
        if not isinstance(target_tab, DocumentView):
            return
        # _on_tab_changed sees _cross_search_results is non-empty and skips
        # closing the toolbar; no manual re-show needed here.
        self._tab_widget.setCurrentIndex(cross_hit.doc_index)
        # Clear stale highlights on non-target tabs.
        for i in range(self._tab_widget.count()):
            tab = self._tab_widget.widget(i)
            if isinstance(tab, DocumentView) and tab is not target_tab:
                tab.page_view.clear_search()
        # Highlight only this hit on the target tab.
        target_tab.page_view.set_search_hits([cross_hit.hit])
        target_tab.page_view.set_current_hit(cross_hit.hit)
        # Update counter + results panel selection.
        docs_with_hits = len({r.doc_index for r in self._cross_search_results})
        self._search_bar.set_aggregate_count(
            len(self._cross_search_results), docs_with_hits, index + 1
        )
        self._results_panel.set_current(index)

    def _on_result_selected(self, index: int) -> None:
        self._jump_to_cross_hit(index)

    def _on_find_next(self) -> None:
        if self._search_bar.search_scope == SearchScope.ALL_OPEN:
            if not self._cross_search_results:
                return
            new_idx = (self._cross_search_index + 1) % len(self._cross_search_results)
            self._jump_to_cross_hit(new_idx)
            return
        if self._active_tab is None or not self._active_tab.search_hits:
            return
        self._active_tab.current_hit_index = (self._active_tab.current_hit_index + 1) % len(
            self._active_tab.search_hits
        )
        self._update_current_hit()

    def _on_find_prev(self) -> None:
        if self._search_bar.search_scope == SearchScope.ALL_OPEN:
            if not self._cross_search_results:
                return
            new_idx = (self._cross_search_index - 1) % len(self._cross_search_results)
            self._jump_to_cross_hit(new_idx)
            return
        if self._active_tab is None or not self._active_tab.search_hits:
            return
        self._active_tab.current_hit_index = (self._active_tab.current_hit_index - 1) % len(
            self._active_tab.search_hits
        )
        self._update_current_hit()

    def _update_current_hit(self) -> None:
        if self._active_tab is None:
            return
        hit = self._active_tab.search_hits[self._active_tab.current_hit_index]
        self._active_tab.page_view.set_current_hit(hit)
        self._search_bar.set_match_count(
            self._active_tab.current_hit_index + 1,
            len(self._active_tab.search_hits),
        )

    def _reset_search_state(self, tab: DocumentView) -> None:
        tab.search_hits = []
        tab.current_hit_index = -1
        tab.page_view.clear_search()
        self._search_bar.clear()

    def _clear_cross_search(self) -> None:
        """Drop cross-search results, hide the dock, clear per-tab highlights."""
        self._cross_search_results = []
        self._cross_search_index = -1
        self._results_panel.clear()
        self._results_dock.setVisible(False)
        for i in range(self._tab_widget.count()):
            tab = self._tab_widget.widget(i)
            if isinstance(tab, DocumentView):
                tab.page_view.clear_search()

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
        if self._active_tab is None:
            self._page_indicator.setText("")
            self._zoom_indicator.setText("")
            return
        page_count = self._active_tab.page_view.page_count
        if page_count == 0:
            self._page_indicator.setText("")
            self._zoom_indicator.setText("")
            return
        current_1based = self._active_tab.page_view.current_page + 1
        self._page_indicator.setText(f"Page {current_1based} of {page_count}")
        zoom = self._active_tab.page_view.effective_zoom
        self._zoom_indicator.setText(f"{int(round(zoom * 100))}%")

    def _update_actions_enabled(self) -> None:
        active = self._active_tab
        has_doc = active is not None and active.page_view.page_count > 0
        current = active.page_view.current_page if active else 0
        page_count = active.page_view.page_count if active else 0

        self.act_close_doc.setEnabled(active is not None)
        self.act_goto_page.setEnabled(has_doc)
        self.act_fit_page.setEnabled(has_doc)
        self.act_fit_width.setEnabled(has_doc)
        self.act_actual_size.setEnabled(has_doc)
        self.act_zoom_in.setEnabled(has_doc)
        self.act_zoom_out.setEnabled(has_doc)
        self.act_find.setEnabled(has_doc)
        self.act_find_next.setEnabled(has_doc)
        self.act_find_prev.setEnabled(has_doc)
        self.act_single_page.setEnabled(has_doc)
        self.act_continuous.setEnabled(has_doc)
        self.act_first_page.setEnabled(has_doc and current > 0)
        self.act_prev_page.setEnabled(has_doc and current > 0)
        self.act_next_page.setEnabled(has_doc and current < page_count - 1)
        self.act_last_page.setEnabled(has_doc and current < page_count - 1)
        self.act_next_tab.setEnabled(self._tab_widget.count() > 1)
        self.act_prev_tab.setEnabled(self._tab_widget.count() > 1)

    def _on_toggle_fullscreen(self) -> None:
        if self._fullscreen_state is None:
            main_tb_visible = (
                self._main_toolbar.isVisible() if self._main_toolbar is not None else True
            )
            self._fullscreen_state = {
                "menubar": self.menuBar().isVisible(),
                "main_toolbar": main_tb_visible,
                "search_toolbar": self._search_toolbar.isVisible(),
                "statusbar": self.statusBar().isVisible(),
                "thumbnail_dock": self._thumbnail_dock.isVisible(),
                "outline_dock": self._outline_dock.isVisible(),
                "results_dock": self._results_dock.isVisible(),
                "tab_bar": self._tab_widget.tabBar().isVisible(),
            }
            self.menuBar().setVisible(False)
            if self._main_toolbar is not None:
                self._main_toolbar.setVisible(False)
            self._search_toolbar.setVisible(False)
            self.statusBar().setVisible(False)
            self._thumbnail_dock.setVisible(False)
            self._outline_dock.setVisible(False)
            self._results_dock.setVisible(False)
            self._tab_widget.tabBar().setVisible(False)
            self.showFullScreen()
            self.act_fullscreen.setChecked(True)
        else:
            state = self._fullscreen_state
            self.menuBar().setVisible(state["menubar"])
            if self._main_toolbar is not None:
                self._main_toolbar.setVisible(state["main_toolbar"])
            self._search_toolbar.setVisible(state["search_toolbar"])
            self.statusBar().setVisible(state["statusbar"])
            self._thumbnail_dock.setVisible(state["thumbnail_dock"])
            self._outline_dock.setVisible(state["outline_dock"])
            self._results_dock.setVisible(state["results_dock"])
            self._tab_widget.tabBar().setVisible(state["tab_bar"])
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
            for i in range(self._tab_widget.count()):
                doc_view = self._tab_widget.widget(i)
                if isinstance(doc_view, DocumentView):
                    doc_view.close_document()
        finally:
            super().closeEvent(event)

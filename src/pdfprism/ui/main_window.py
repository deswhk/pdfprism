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
    QInputDialog,
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
from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.exceptions import (
    EncryptionOperationError,
    PasswordRequiredError,
    PdfPrismError,
)
from pdfprism.core.types import CrossDocHit
from pdfprism.services.extract import ExtractService
from pdfprism.services.pages import PageService
from pdfprism.services.pages import merge as merge_documents
from pdfprism.services.properties import PropertiesService
from pdfprism.services.redaction import RedactionService
from pdfprism.services.search import SearchScope, SearchService
from pdfprism.ui.dialogs.about import AboutDialog
from pdfprism.ui.dialogs.crop import CropDialog
from pdfprism.ui.dialogs.crypt import CryptDialog
from pdfprism.ui.dialogs.extract import ExtractDialog, ExtractKind
from pdfprism.ui.dialogs.extract_pages import ExtractPagesDialog
from pdfprism.ui.dialogs.goto_page import GotoPageDialog
from pdfprism.ui.dialogs.insert_pages import InsertPagesDialog
from pdfprism.ui.dialogs.merge import MergeDialog
from pdfprism.ui.dialogs.password import PasswordDialog
from pdfprism.ui.dialogs.properties import PropertiesDialog
from pdfprism.ui.dialogs.search_redact import SearchRedactDialog
from pdfprism.ui.dialogs.split import SplitDialog
from pdfprism.ui.theme import DARK_QSS
from pdfprism.ui.widgets.document_view import DocumentView
from pdfprism.ui.widgets.page_view import ToolMode, ViewMode
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
        self._tool_mode: ToolMode = ToolMode(
            settings.value("tool/mode", ToolMode.HAND.value, type=str)
        )
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
        self._organize_stack = QStackedWidget(self)
        self._organize_stack.addWidget(QWidget(self))
        self._outline_stack.addWidget(QWidget(self))

        self._thumbnail_dock = self._make_dock("Thumbnails", self._thumbnail_stack)
        self._outline_dock = self._make_dock("Outline", self._outline_stack)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._thumbnail_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._outline_dock)
        self.tabifyDockWidget(self._thumbnail_dock, self._outline_dock)
        self._thumbnail_dock.raise_()

        # Organize Pages dock (right by default, hidden by default; F6
        # toggle). Power-user surface for multi-select + drag-reorder.
        self._organize_dock = self._make_dock("Organize Pages", self._organize_stack)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._organize_dock)
        self._organize_dock.setVisible(False)

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
        self._tool_indicator = QLabel("")
        self.statusBar().addPermanentWidget(self._page_indicator)
        self.statusBar().addPermanentWidget(self._zoom_indicator)
        self.statusBar().addPermanentWidget(self._tool_indicator)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self.addToolBarBreak()
        self.addToolBar(self._search_toolbar)

        self.act_toggle_dark_mode.setChecked(self._dark_mode)
        self._apply_theme()
        self._sync_tool_mode_ui()
        self._update_recent_menu()
        self._update_status_bar()
        self._update_actions_enabled()
        self._refresh_save_actions()

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

        self.act_save = QAction("&Save", self)
        self.act_save.setShortcut(QKeySequence.StandardKey.Save)
        self.act_save.triggered.connect(self._on_save)
        self.act_save.setEnabled(False)

        self.act_save_as = QAction("Save &As...", self)
        self.act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.act_save_as.triggered.connect(self._on_save_as)
        self.act_save_as.setEnabled(False)

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

        self.act_tool_hand = QAction("&Hand Tool", self)
        self.act_tool_hand.setShortcut("H")
        self.act_tool_hand.setCheckable(True)
        self.act_tool_hand.triggered.connect(lambda: self._on_set_tool_mode(ToolMode.HAND))

        self.act_tool_select = QAction("&Select Text", self)
        self.act_tool_select.setShortcut("V")
        self.act_tool_select.setCheckable(True)
        self.act_tool_select.triggered.connect(lambda: self._on_set_tool_mode(ToolMode.SELECT))

        # PR 12: redaction mode -- click-drag on a page draws a
        # pending redaction rectangle. Actual rectangle drawing
        # logic is in PageView (sub-step 6).
        self.act_tool_redaction = QAction("&Redaction Mode", self)
        self.act_tool_redaction.setShortcut("R")
        self.act_tool_redaction.setCheckable(True)
        self.act_tool_redaction.triggered.connect(
            lambda: self._on_set_tool_mode(ToolMode.REDACTION)
        )
        self.act_tool_redaction.setToolTip("Draw redaction marks on the page")

        self.act_copy = QAction("&Copy", self)
        self.act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        self.act_copy.triggered.connect(self._on_copy)

        self.act_extract_text = QAction("Extract &Text...", self)
        self.act_extract_text.triggered.connect(self._on_extract_text)

        # Page operations (PR 8). All act on the current page in the
        # active tab; route through DocumentView so the modified flag
        # updates and the page/thumbnail UI rebuilds.
        self.act_rotate_right = QAction("Rotate &Right (90°)", self)
        self.act_rotate_right.setShortcut(QKeySequence("Ctrl+R"))
        self.act_rotate_right.triggered.connect(self._on_rotate_right)
        self.act_rotate_right.setEnabled(False)

        self.act_rotate_left = QAction("Rotate &Left (90°)", self)
        self.act_rotate_left.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self.act_rotate_left.triggered.connect(self._on_rotate_left)
        self.act_rotate_left.setEnabled(False)

        self.act_rotate_180 = QAction("Rotate 180°", self)
        self.act_rotate_180.triggered.connect(self._on_rotate_180)
        self.act_rotate_180.setEnabled(False)

        self.act_delete_page = QAction("&Delete Current Page", self)
        self.act_delete_page.triggered.connect(self._on_delete_page)
        self.act_delete_page.setEnabled(False)

        self.act_insert_blank = QAction("&Insert Blank Page After", self)
        self.act_insert_blank.triggered.connect(self._on_insert_blank)
        self.act_insert_blank.setEnabled(False)

        self.act_duplicate_page = QAction("D&uplicate Current Page", self)
        self.act_duplicate_page.triggered.connect(self._on_duplicate_page)
        self.act_duplicate_page.setEnabled(False)

        self.act_move_page = QAction("&Move Page...", self)
        self.act_move_page.setShortcut(QKeySequence("Ctrl+Shift+M"))
        self.act_move_page.triggered.connect(self._on_move_page)
        self.act_move_page.setEnabled(False)

        self.act_crop_page = QAction("&Crop Page...", self)
        self.act_crop_page.triggered.connect(self._on_crop_page)
        self.act_crop_page.setEnabled(False)

        self.act_crop_selection = QAction("Crop &Selection...", self)
        self.act_crop_selection.triggered.connect(self._on_organize_crop_selection)
        self.act_crop_selection.setEnabled(False)
        self.act_crop_selection.setToolTip(
            "Crop selected pages in the Organize panel with the same margins"
        )

        self.act_extract_images = QAction("Extract &Images...", self)
        self.act_extract_images.triggered.connect(self._on_extract_images)

        # Cross-document page operations (PR 8.5).
        self.act_extract_pages = QAction("&Extract Pages to File...", self)
        self.act_extract_pages.triggered.connect(self._on_extract_pages)
        self.act_extract_pages.setEnabled(False)

        self.act_extract_selection = QAction("Extract Selectio&n...", self)
        self.act_extract_selection.triggered.connect(self._on_organize_extract_selection)
        self.act_extract_selection.setEnabled(False)
        self.act_extract_selection.setToolTip(
            "Save selected pages from the Organize panel as a new PDF"
        )

        self.act_security_password = QAction("&Password...", self)
        self.act_security_password.triggered.connect(self._on_security_password)
        self.act_security_password.setEnabled(False)
        self.act_security_password.setToolTip(
            "Set, change, or remove the password on this document"
        )

        # PR 11: metadata view / edit / sanitize
        self.act_properties = QAction("P&roperties...", self)
        self.act_properties.triggered.connect(self._on_file_properties)
        self.act_properties.setEnabled(False)
        self.act_properties.setToolTip("View, edit, or sanitize document metadata")

        # PR 12: redaction menu actions.
        self.act_redaction_apply = QAction("&Apply Redactions...", self)
        self.act_redaction_apply.triggered.connect(self._on_redaction_apply)
        self.act_redaction_apply.setEnabled(False)
        self.act_redaction_apply.setToolTip(
            "Destructively apply all pending redactions to the document"
        )

        self.act_redaction_clear = QAction("&Clear All Pending", self)
        self.act_redaction_clear.triggered.connect(self._on_redaction_clear)
        self.act_redaction_clear.setEnabled(False)
        self.act_redaction_clear.setToolTip("Remove all pending redaction marks without applying")

        # PR 12.2: search-then-redact.
        self.act_redaction_search = QAction("&Search and Redact...", self)
        self.act_redaction_search.triggered.connect(self._on_redaction_search)
        self.act_redaction_search.setEnabled(False)
        self.act_redaction_search.setToolTip(
            "Search across the document and redact selected matches"
        )

        self.act_insert_pages = QAction("&Insert Pages from File...", self)
        self.act_insert_pages.triggered.connect(self._on_insert_pages)
        self.act_insert_pages.setEnabled(False)

        self.act_split = QAction("&Split Document...", self)
        self.act_split.triggered.connect(self._on_split)
        self.act_split.setEnabled(False)

        self.act_merge = QAction("&Merge Documents...", self)
        self.act_merge.triggered.connect(self._on_merge)
        self.act_merge.setEnabled(False)

        self._tool_action_group = QActionGroup(self)
        self._tool_action_group.addAction(self.act_tool_hand)
        self._tool_action_group.addAction(self.act_tool_select)
        self._tool_action_group.addAction(self.act_tool_redaction)
        self._tool_action_group.setExclusive(True)

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
        self.act_toggle_organize = self._organize_dock.toggleViewAction()
        self.act_toggle_organize.setText("&Organize Pages")
        self.act_toggle_organize.setShortcut("F6")

        self.act_about = QAction("&About pdfprism", self)
        self.act_about.triggered.connect(self._on_about)
        self.act_toggle_outline.setText("&Outline")
        self.act_toggle_outline.setShortcut("F5")

        for action in [
            self.act_open,
            self.act_save,
            self.act_save_as,
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
            self.act_tool_hand,
            self.act_tool_select,
            self.act_tool_redaction,
            self.act_copy,
            self.act_extract_text,
            self.act_extract_images,
            self.act_extract_pages,
            self.act_insert_pages,
            self.act_split,
            self.act_merge,
            self.act_rotate_right,
            self.act_rotate_left,
            self.act_rotate_180,
            self.act_delete_page,
            self.act_insert_blank,
            self.act_duplicate_page,
            self.act_move_page,
            self.act_crop_page,
            self.act_fit_page,
            self.act_fit_width,
            self.act_actual_size,
            self.act_zoom_in,
            self.act_zoom_out,
            self.act_toggle_thumbnails,
            self.act_toggle_outline,
            self.act_toggle_organize,
            self.act_about,
        ]:
            self.addAction(action)

    def _build_menus(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.act_open)
        self._recent_menu = file_menu.addMenu("Open &Recent")
        file_menu.addSeparator()
        file_menu.addAction(self.act_save)
        file_menu.addAction(self.act_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self.act_close_doc)
        extract_menu = file_menu.addMenu("&Extract")
        extract_menu.addAction(self.act_extract_text)
        extract_menu.addAction(self.act_extract_images)
        pages_menu = file_menu.addMenu("&Pages")
        pages_menu.addAction(self.act_extract_pages)
        pages_menu.addAction(self.act_extract_selection)
        pages_menu.addAction(self.act_insert_pages)
        pages_menu.addSeparator()
        pages_menu.addAction(self.act_split)
        pages_menu.addAction(self.act_merge)
        security_menu = file_menu.addMenu("Se&curity")
        security_menu.addAction(self.act_security_password)
        file_menu.addAction(self.act_properties)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(self.act_find)
        edit_menu.addAction(self.act_find_next)
        edit_menu.addAction(self.act_find_prev)
        edit_menu.addSeparator()
        page_menu = edit_menu.addMenu("&Page")
        page_menu.addAction(self.act_rotate_right)
        page_menu.addAction(self.act_rotate_left)
        page_menu.addAction(self.act_rotate_180)
        page_menu.addSeparator()
        page_menu.addAction(self.act_insert_blank)
        page_menu.addAction(self.act_duplicate_page)
        page_menu.addAction(self.act_move_page)
        page_menu.addAction(self.act_crop_page)
        page_menu.addAction(self.act_crop_selection)
        page_menu.addSeparator()
        page_menu.addAction(self.act_delete_page)

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
        view_menu.addAction(self.act_toggle_organize)

        # PR 12: Redaction menu (right after View, before Help).
        redaction_menu = menubar.addMenu("&Redaction")
        redaction_menu.addAction(self.act_redaction_apply)
        redaction_menu.addAction(self.act_redaction_clear)
        redaction_menu.addSeparator()
        redaction_menu.addAction(self.act_redaction_search)

        view_menu.addSeparator()
        view_menu.addAction(self.act_fullscreen)
        view_menu.addAction(self.act_toggle_dark_mode)
        view_menu.addSeparator()
        view_menu.addAction(self.act_tool_hand)
        view_menu.addAction(self.act_tool_select)
        view_menu.addAction(self.act_tool_redaction)

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

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(self.act_about)

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
        self._organize_stack.addWidget(doc_view.organize_panel)
        tab_idx = self._tab_widget.addTab(doc_view, doc_view.path.name)
        self._tab_widget.setTabToolTip(tab_idx, str(doc_view.path))
        doc_view.modified_changed.connect(
            lambda modified, dv=doc_view: self._on_tab_modified_changed(dv, modified)
        )
        return tab_idx

    def _on_tab_close_requested(self, index: int) -> None:
        doc_view = self._tab_widget.widget(index)
        if not isinstance(doc_view, DocumentView):
            return
        if doc_view.is_modified and not self._prompt_unsaved_changes(doc_view):
            return
        # Cross-search results index tabs by position; removing a tab
        # invalidates those indices, so drop the result set rather than
        # try to remap.
        if self._cross_search_results:
            self._clear_cross_search()
        self._thumbnail_stack.removeWidget(doc_view.thumbnail_panel)
        self._outline_stack.removeWidget(doc_view.outline_panel)
        self._organize_stack.removeWidget(doc_view.organize_panel)
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
                # PR 9.5: disconnect organize_panel selection
                # subscription. Use a broad disconnect (no slot arg)
                # because the connect used a lambda which can't be
                # referenced by handle.
                try:
                    self._active_tab.organize_panel.selection_changed.disconnect()
                except (RuntimeError, TypeError):
                    pass
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
        organize_idx = self._organize_stack.indexOf(doc_view.organize_panel)
        if organize_idx >= 0:
            self._organize_stack.setCurrentIndex(organize_idx)
        outline_idx = self._outline_stack.indexOf(doc_view.outline_panel)
        if outline_idx >= 0:
            self._outline_stack.setCurrentIndex(outline_idx)

        doc_view.page_changed.connect(self._on_page_changed)
        doc_view.zoom_changed.connect(self._on_zoom_changed)
        doc_view.view_mode_changed.connect(self._on_view_mode_changed)
        # PR 9.5: refresh selection-based actions when the user
        # selects/deselects pages in the Organize panel of the
        # active tab. Uses _refresh_save_actions because that's
        # where act_crop_selection / act_extract_selection are
        # toggled. Lambda ignores the emitted indices arg.
        doc_view.organize_panel.selection_changed.connect(
            lambda _indices: self._refresh_save_actions()
        )

        mode = doc_view.page_view.view_mode
        if mode == ViewMode.SINGLE_PAGE:
            self.act_single_page.setChecked(True)
        else:
            self.act_continuous.setChecked(True)
        self.setWindowTitle(f"pdfprism - {doc_view.path.name}")
        self._update_status_bar()
        self._update_actions_enabled()
        self._refresh_save_actions()
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
        self._organize_stack.setCurrentIndex(0)
        self.setWindowTitle("pdfprism")
        if self._search_toolbar.isVisible():
            self._on_close_search()
        self._clear_cross_search()
        self._update_status_bar()
        self._refresh_save_actions()
        self._update_actions_enabled()
        self._refresh_save_actions()

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

        # First attempt with no password. Encrypted PDFs raise
        # PasswordRequiredError; _try_open dispatches to the
        # password prompt + retry loop when that happens.
        doc_view = self._try_open(path, password=None)
        if doc_view is None:
            # Either non-password failure (already surfaced to user)
            # or user cancelled the password prompt.
            return

        tab_idx = self._add_tab(doc_view)
        self._tab_widget.setCurrentIndex(tab_idx)
        doc_view.page_view.set_tool_mode(self._tool_mode)
        doc_view.page_view.copy_requested.connect(self._on_copy)
        doc_view.page_view.extract_selection_requested.connect(self._on_extract_selection)
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
        snippets = self._build_snippets_for_cross_results(results)
        self._results_panel.set_results(results, titles, snippets)
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
        self._refresh_save_actions()

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
                "organize_dock": self._organize_dock.isVisible(),
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
            self._organize_dock.setVisible(False)
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
            self._organize_dock.setVisible(state.get("organize_dock", False))
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

    def _on_set_tool_mode(self, mode: ToolMode) -> None:
        if mode == self._tool_mode:
            return
        self._tool_mode = mode
        settings = QSettings()
        settings.setValue("tool/mode", mode.value)
        self._sync_tool_mode_ui()
        self._apply_tool_mode_to_all_tabs()

    def _sync_tool_mode_ui(self) -> None:
        """Keep menu checkmarks and status indicator in sync with the
        current tool mode."""
        if self._tool_mode == ToolMode.HAND:
            self.act_tool_hand.setChecked(True)
            self._tool_indicator.setText("Hand")
        elif self._tool_mode == ToolMode.REDACTION:
            self.act_tool_redaction.setChecked(True)
            self._tool_indicator.setText("Redaction")
        else:
            self.act_tool_select.setChecked(True)
            self._tool_indicator.setText("Select")

    def _apply_tool_mode_to_all_tabs(self) -> None:
        """Push the current tool mode into every open tab's PageView."""
        for i in range(self._tab_widget.count()):
            tab = self._tab_widget.widget(i)
            if isinstance(tab, DocumentView):
                tab.page_view.set_tool_mode(self._tool_mode)

    def _on_copy(self) -> None:
        """Ctrl+C handler. Copies the active tab's selected text to the
        system clipboard. Silently no-ops when nothing is selected or no
        tab is active -- matches how other apps treat empty-selection Copy."""
        if self._active_tab is None:
            return
        text = self._active_tab.page_view.selected_text
        if not text:
            return
        app = QApplication.instance()
        if isinstance(app, QApplication):
            clipboard = app.clipboard()
            if clipboard is not None:
                clipboard.setText(text)

    def _on_extract_selection(self) -> None:
        """Right-click "Extract Selection to File..." handler. Saves the
        active tab's selected text to a .txt file chosen by the user."""
        if self._active_tab is None:
            return
        text = self._active_tab.page_view.selected_text
        if not text:
            return
        settings = QSettings()
        last_dir = settings.value("extract/last_dir", "", type=str)
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save Selection", last_dir, "Text files (*.txt);;All files (*)"
        )
        if not path_str:
            return
        path = Path(path_str)
        settings.setValue("extract/last_dir", str(path.parent))
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", f"Could not write {path}: {exc}")

    def _on_extract_text(self) -> None:
        """File -> Extract -> Text... slot. Extracts the chosen page
        range to a single .txt file (form-feed between pages).
        """
        if self._active_tab is None:
            return
        page_count = self._active_tab.page_view.page_count
        if page_count == 0:
            return
        dialog = ExtractDialog(page_count, ExtractKind.TEXT, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        settings = QSettings()
        last_dir = settings.value("extract/last_dir", "", type=str)
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save extracted text",
            last_dir,
            "Text files (*.txt);;All files (*)",
        )
        if not path_str:
            return
        out_path = Path(path_str)
        settings.setValue("extract/last_dir", str(out_path.parent))
        service = ExtractService(self._active_tab.adapter)
        text = service.text_full_document(page_range=dialog.page_range)
        try:
            out_path.write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Save failed",
                f"Could not write {out_path}: {exc}",
            )

    def _on_extract_images(self) -> None:
        """File -> Extract -> Images... slot. Extracts the chosen page
        range to a chosen directory; one file per image, named
        ``page<N>_img<M>.<ext>``.
        """
        if self._active_tab is None:
            return
        page_count = self._active_tab.page_view.page_count
        if page_count == 0:
            return
        dialog = ExtractDialog(page_count, ExtractKind.IMAGES, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        settings = QSettings()
        last_dir = settings.value("extract/last_dir", "", type=str)
        out_dir_str = QFileDialog.getExistingDirectory(self, "Choose output directory", last_dir)
        if not out_dir_str:
            return
        out_dir = Path(out_dir_str)
        settings.setValue("extract/last_dir", str(out_dir))
        service = ExtractService(self._active_tab.adapter)
        try:
            written = service.images_full_document(out_dir, page_range=dialog.page_range)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Extract failed",
                f"Could not write to {out_dir}: {exc}",
            )
            return
        QMessageBox.information(
            self,
            "Extract complete",
            f"Wrote {len(written)} image(s) to {out_dir}",
        )

    def _build_snippets_for_cross_results(self, results: list[CrossDocHit]) -> list[str]:
        """Build a parallel snippet list for cross-search hits.

        One ExtractService per doc index, cached locally so we do not
        re-wrap the same adapter once per hit. Empty string on any
        extraction failure -- the panel falls back to plain Page N.
        """
        snippets: list[str] = []
        services: dict[int, ExtractService] = {}
        for r in results:
            try:
                service = services.get(r.doc_index)
                if service is None:
                    tab = self._tab_widget.widget(r.doc_index)
                    if not isinstance(tab, DocumentView):
                        snippets.append("")
                        continue
                    service = ExtractService(tab.adapter)
                    services[r.doc_index] = service
                snippets.append(
                    service.snippet_around(
                        r.hit.page_index,
                        (
                            r.hit.x0,
                            r.hit.y0,
                            r.hit.x1,
                            r.hit.y1,
                        ),
                    )
                )
            except Exception:
                snippets.append("")
        return snippets

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

    def _on_organize_crop_selection(self) -> None:
        """Edit -> Page -> Crop Selection... slot (Organize panel delegate).

        Delegates to the active tab's OrganizePagesPanel,
        which handles the dialog + emission. MainWindow's
        role is discoverability (menu entry) and enable/
        disable based on selection state; the actual
        implementation lives on the panel to avoid
        duplicating dialog + margin-validation logic.
        """
        tab = self._active_tab
        if tab is None:
            return
        tab.organize_panel._on_crop_requested()

    def _on_organize_extract_selection(self) -> None:
        """File -> Pages -> Extract Selection... slot (Organize panel delegate).

        Delegates to the active tab's OrganizePagesPanel,
        which handles the Save-As dialog + filename
        suggestion + emission. Same reasoning as
        _on_crop_selection.
        """
        tab = self._active_tab
        if tab is None:
            return
        tab.organize_panel._on_extract_requested()

    def _on_security_password(self) -> None:
        """File -> Security -> Password... slot.

        Opens CryptDialog in the appropriate mode based on the
        active tab's encryption state, then delegates to the
        SecurityService method matching the user's intent.

        For the destructive Remove branch, a confirmation
        prompt gates the actual removal -- accidentally
        producing an unpassword-protected copy of a
        sensitive document would be a serious data-security
        regression.
        """
        tab = self._active_tab
        if tab is None:
            return
        is_encrypted = tab.adapter.get_document_info().needs_password
        dlg = CryptDialog(is_encrypted, tab.path.name, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            if dlg.remove_requested:
                confirm = QMessageBox.question(
                    self,
                    "Remove Password?",
                    (
                        f'This will save "{tab.path.name}" without a '
                        "password. Anyone with access to the file will be "
                        "able to open it. Continue?"
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if confirm != QMessageBox.StandardButton.Yes:
                    return
                tab.remove_password()
            elif is_encrypted:
                tab.change_password(dlg.new_password)
            else:
                tab.set_password(dlg.new_password)
        except EncryptionOperationError as exc:
            QMessageBox.critical(self, "Password Operation Failed", str(exc))
            return
        except PdfPrismError as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))
            return

        self._refresh_save_actions()

    def _on_file_properties(self) -> None:
        """Open PropertiesDialog for the active tab; apply on OK."""
        tab = self._active_tab
        if tab is None:
            return
        adapter = tab._adapter
        try:
            current = adapter.get_metadata()
        except PdfPrismError as exc:
            QMessageBox.critical(self, "Cannot load metadata", str(exc))
            return
        dlg = PropertiesDialog(current, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updates = dlg.get_updates()
        delete_xmp = dlg.delete_xmp_requested
        service = PropertiesService(adapter)
        try:
            service.set_metadata(updates)
            if delete_xmp:
                adapter.delete_xml_metadata()
            adapter.save()
        except PdfPrismError as exc:
            QMessageBox.critical(self, "Failed to update properties", str(exc))
            return
        tab._refresh_modified()

    def _on_redaction_apply(self) -> None:
        """Apply all pending redactions on the active tab (destructive)."""
        tab = self._active_tab
        if tab is None:
            return
        adapter = tab._adapter
        service = RedactionService(adapter)
        pending = service.list_redactions()
        if not pending:
            QMessageBox.information(
                self,
                "No redactions",
                "There are no pending redaction marks to apply.",
            )
            return
        # Confirmation dialog with count.
        page_count = len({r.page_index for r in pending})
        msg = (
            f"This will permanently redact {len(pending)} region(s) "
            f"across {page_count} page(s). This cannot be undone. Continue?"
        )
        reply = QMessageBox.question(
            self,
            "Apply Redactions",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            count = service.apply()
            adapter.save()
        except PdfPrismError as exc:
            QMessageBox.critical(self, "Failed to apply redactions", str(exc))
            return
        tab._refresh_modified()
        # Re-render since content is now different.
        tab._page_cache.clear()
        tab._page_view.set_adapter(adapter)
        tab._thumbnail_panel.set_adapter(adapter)
        self.statusBar().showMessage(f"Applied {count} redaction(s)", 3000)

    def _on_redaction_clear(self) -> None:
        """Remove all pending redaction marks without applying."""
        tab = self._active_tab
        if tab is None:
            return
        adapter = tab._adapter
        service = RedactionService(adapter)
        pending = service.list_redactions()
        if not pending:
            self.statusBar().showMessage("No pending redactions", 3000)
            return
        # Delete in reverse order per page so indices stay valid.
        # Group by page first.
        by_page: dict[int, list[int]] = {}
        # list_redactions returns page-major order; enumerate to get
        # each redaction's index within its page.
        page_local_index: dict[int, int] = {}
        for r in pending:
            i = page_local_index.get(r.page_index, 0)
            by_page.setdefault(r.page_index, []).append(i)
            page_local_index[r.page_index] = i + 1
        for page_index, indices in by_page.items():
            for i in reversed(indices):
                adapter.remove_redaction(page_index, i)
        tab._refresh_modified()
        tab._page_cache.clear()
        tab._page_view.set_adapter(adapter)
        tab._thumbnail_panel.set_adapter(adapter)
        self.statusBar().showMessage(f"Cleared {len(pending)} pending redaction(s)", 3000)

    def _on_redaction_search(self) -> None:
        """Open SearchRedactDialog; commit selected hits as pending redactions."""
        tab = self._active_tab
        if tab is None:
            return
        adapter = tab._adapter
        dlg = SearchRedactDialog(adapter, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        hits = dlg.selected_hits()
        if not hits:
            return
        service = RedactionService(adapter)
        try:
            count = service.redact_hits(hits)
        except PdfPrismError as exc:
            QMessageBox.critical(self, "Failed to add redactions", str(exc))
            return
        if not count:
            return
        tab._refresh_modified()
        tab._page_cache.clear()
        tab._page_view.set_adapter(adapter)
        tab._thumbnail_panel.set_adapter(adapter)
        self.statusBar().showMessage(f"Added {count} pending redaction(s) from search", 3000)

    def _on_about(self) -> None:
        """Help -> About slot: show the modal About dialog."""
        AboutDialog(self).exec()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        for i in range(self._tab_widget.count()):
            doc_view = self._tab_widget.widget(i)
            if isinstance(doc_view, DocumentView) and doc_view.is_modified:
                if not self._prompt_unsaved_changes(doc_view):
                    event.ignore()
                    return
        try:
            for i in range(self._tab_widget.count()):
                doc_view = self._tab_widget.widget(i)
                if isinstance(doc_view, DocumentView):
                    doc_view.close_document()
        finally:
            super().closeEvent(event)

    # ----- save / modified-tracking slots -----

    def _on_extract_pages(self) -> None:
        """File -> Pages -> Extract Pages to File... slot."""
        tab = self._active_tab
        if tab is None:
            return
        dlg = ExtractPagesDialog(
            source_path=tab.path,
            page_count=tab.page_view.page_count,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        from_idx, to_idx = dlg.page_range
        try:
            PageService(tab.adapter).extract_to_file(from_idx, to_idx, dlg.output_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Extract Pages", str(exc))
            return
        self.statusBar().showMessage(f"Wrote {dlg.output_path.name}", 5000)

    def _on_insert_pages(self) -> None:
        """File -> Pages -> Insert Pages from File... slot."""
        tab = self._active_tab
        if tab is None:
            return
        settings = QSettings()
        last_dir = settings.value("recent/last_dir", "", type=str)
        source_str, _ = QFileDialog.getOpenFileName(
            self,
            "Select Source PDF",
            last_dir,
            "PDF files (*.pdf);;All files (*)",
        )
        if not source_str:
            return
        source_path = Path(source_str)
        # Read source page count headlessly to bound the dialog.
        probe = PyMuPDFAdapter()
        try:
            probe.open(source_path)
            source_count = probe.page_count
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "Insert Pages",
                f"Cannot open {source_path.name}: {exc}",
            )
            return
        finally:
            probe.close()
        current_page = tab.page_view.current_page
        dlg = InsertPagesDialog(
            source_path=source_path,
            source_page_count=source_count,
            target_name=tab.path.name,
            target_page_count=tab.page_view.page_count,
            default_target_position=current_page + 2,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        from_idx, to_idx = dlg.source_range
        try:
            tab.insert_from(source_path, from_idx, to_idx, dlg.target_position)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Insert Pages", str(exc))

    def _on_split(self) -> None:
        """File -> Pages -> Split Document... slot."""
        tab = self._active_tab
        if tab is None:
            return
        dlg = SplitDialog(
            source_path=tab.path,
            page_count=tab.page_view.page_count,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            paths = PageService(tab.adapter).split(dlg.breakpoints, dlg.output_dir, dlg.stem)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Split", str(exc))
            return
        names = "\n".join(p.name for p in paths)
        QMessageBox.information(
            self,
            "Split",
            f"Wrote {len(paths)} file(s) to {dlg.output_dir}:\n\n{names}",
        )

    def _on_merge(self) -> None:
        """File -> Pages -> Merge Documents... slot."""
        n = self._tab_widget.count()
        if n < 2:
            return
        settings = QSettings()
        last_dir = settings.value("recent/last_dir", "", type=str)
        titles = [self._tab_widget.tabText(i) for i in range(n)]
        default = Path(last_dir) / "merged.pdf" if last_dir else Path("merged.pdf")
        dlg = MergeDialog(tab_titles=titles, default_output_path=default, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sources = [self._tab_widget.widget(i).adapter for i in dlg.selected_tab_indices]
        try:
            merge_documents(sources, dlg.output_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Merge", str(exc))
            return
        # Open the merged result as a new tab.
        self._open_path(dlg.output_path)

    def _on_save(self) -> None:
        if self._active_tab is None:
            return
        if not self._active_tab.is_modified:
            return
        try:
            self._active_tab.save()
        except Exception as exc:  # noqa: BLE001 - surfaced to user
            QMessageBox.critical(self, "Save Failed", str(exc))
            return
        self._refresh_save_actions()

    def _on_save_as(self) -> None:
        if self._active_tab is None:
            return
        settings = QSettings()
        last_dir = settings.value("recent/last_dir", "", type=str)
        # Suggest <stem> (copy).pdf as a default to avoid clobbering.
        suggested = self._active_tab.path.parent / f"{self._active_tab.path.stem} (copy).pdf"
        start_dir = last_dir or str(suggested)
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save PDF As",
            start_dir if last_dir else str(suggested),
            "PDF files (*.pdf);;All files (*)",
        )
        if not path_str:
            return
        target = Path(path_str)
        if target.suffix.lower() != ".pdf":
            target = target.with_suffix(".pdf")
        try:
            self._active_tab.save_as(target)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save As Failed", str(exc))
            return
        settings.setValue("recent/last_dir", str(target.parent))
        # Path changed -> update tab title + tooltip.
        idx = self._tab_widget.indexOf(self._active_tab)
        if idx >= 0:
            self._tab_widget.setTabText(idx, target.name)
            self._tab_widget.setTabToolTip(idx, str(target))
        self._refresh_save_actions()

    def _on_tab_modified_changed(self, doc_view: DocumentView, modified: bool) -> None:
        idx = self._tab_widget.indexOf(doc_view)
        if idx < 0:
            return
        base = doc_view.path.name
        self._tab_widget.setTabText(idx, f"{base} *" if modified else base)
        if doc_view is self._active_tab:
            self._refresh_save_actions()

    def _refresh_save_actions(self) -> None:
        has_tab = self._active_tab is not None
        self.act_save.setEnabled(has_tab and self._active_tab.is_modified)
        self.act_save_as.setEnabled(has_tab)
        # Page operations also enable/disable with active tab.
        for act in (
            self.act_rotate_right,
            self.act_rotate_left,
            self.act_rotate_180,
            self.act_delete_page,
            self.act_insert_blank,
            self.act_duplicate_page,
            self.act_move_page,
            self.act_crop_page,
            self.act_extract_pages,
            self.act_insert_pages,
            self.act_split,
        ):
            act.setEnabled(has_tab)

        # PR 9.5: crop/extract selection actions enable only
        # when (a) a tab is open AND (b) that tab's Organize
        # panel has a non-empty selection. Selection state is
        # tracked via organize_panel.selection_changed
        # (subscribed in _on_current_tab_changed).
        has_selection = has_tab and len(self._active_tab.organize_panel.selected_indices) > 0
        self.act_crop_selection.setEnabled(has_selection)
        self.act_extract_selection.setEnabled(has_selection)
        # PR 10.5: security action -- enables with any open tab.
        self.act_security_password.setEnabled(has_tab)
        self.act_properties.setEnabled(has_tab)
        # PR 12: redaction actions enabled with any open tab.
        # Empty-pending case handled inside the slots.
        self.act_redaction_apply.setEnabled(has_tab)
        self.act_redaction_clear.setEnabled(has_tab)
        self.act_redaction_search.setEnabled(has_tab)
        # Merge requires at least 2 open tabs.
        self.act_merge.setEnabled(self._tab_widget.count() >= 2)

    def _try_open(self, path: Path, password: str | None) -> DocumentView | None:
        """Attempt to open ``path`` with an optional password.

        Returns the constructed and opened ``DocumentView`` on
        success. Returns ``None`` in two failure modes:
        (1) a non-password open failure was surfaced to the user
        via a critical dialog, or (2) the user cancelled the
        password prompt loop.

        On ``PasswordRequiredError`` this method delegates to
        ``_prompt_for_password`` which runs the retry loop.
        """
        doc_view = DocumentView(path, self)
        try:
            doc_view.open(password=password)
        except PasswordRequiredError:
            doc_view.deleteLater()
            return self._prompt_for_password(path)
        except PdfPrismError as exc:
            logger.exception("Failed to open %s", path)
            doc_view.deleteLater()
            QMessageBox.critical(self, "Open failed", str(exc))
            return None
        return doc_view

    def _prompt_for_password(self, path: Path) -> DocumentView | None:
        """Show a PasswordDialog and retry open() until success or Cancel.

        The dialog instance is reused across attempts so the
        modal stays in the same screen position and the retry
        loop feels like one continuous interaction. Wrong-
        password attempts show an inline banner via
        ``set_error_message``. Unlimited retries; the user
        cancels via Cancel or Esc, at which point we return
        ``None``.
        """
        dlg = PasswordDialog(path.name, self)
        while True:
            if dlg.exec() != QDialog.DialogCode.Accepted:
                # User cancelled: give up quietly. Path is not
                # added to Recent Files (no successful open).
                return None
            password = dlg.password
            doc_view = DocumentView(path, self)
            try:
                doc_view.open(password=password)
                return doc_view
            except PasswordRequiredError:
                # Wrong password. Show inline error, keep looping.
                doc_view.deleteLater()
                dlg.set_error_message("Incorrect password. Try again.")
            except PdfPrismError as exc:
                # Any other error post-auth: surface + give up.
                logger.exception("Failed to open %s", path)
                doc_view.deleteLater()
                QMessageBox.critical(self, "Open failed", str(exc))
                return None

    def _prompt_unsaved_changes(self, doc_view: DocumentView) -> bool:
        """Modal prompt for a modified document.

        Returns True if it is safe to proceed (saved, or user chose to
        discard), False if the user cancelled.
        """
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            f"'{doc_view.path.name}' has unsaved changes. Save before closing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return False
        if reply == QMessageBox.StandardButton.Save:
            try:
                doc_view.save()
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Save Failed", str(exc))
                return False
        return True

    # ----- page-op slots -----

    def _current_page_index(self) -> int | None:
        if self._active_tab is None:
            return None
        idx = self._active_tab.page_view.current_page
        if idx < 0 or idx >= self._active_tab.page_view.page_count:
            return None
        return idx

    def _run_page_op(self, action_label: str, fn) -> None:
        """Wrap a page-op call: surface engine errors via QMessageBox."""
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, action_label, str(exc))

    def _on_rotate_right(self) -> None:
        idx = self._current_page_index()
        if idx is None:
            return
        self._run_page_op(
            "Rotate Right",
            lambda: self._active_tab.rotate_page(idx, 90),
        )

    def _on_rotate_left(self) -> None:
        idx = self._current_page_index()
        if idx is None:
            return
        self._run_page_op(
            "Rotate Left",
            lambda: self._active_tab.rotate_page(idx, 270),
        )

    def _on_rotate_180(self) -> None:
        idx = self._current_page_index()
        if idx is None:
            return
        self._run_page_op(
            "Rotate 180°",
            lambda: self._active_tab.rotate_page(idx, 180),
        )

    def _on_delete_page(self) -> None:
        idx = self._current_page_index()
        if idx is None:
            return
        if self._active_tab.page_view.page_count <= 1:
            QMessageBox.warning(
                self,
                "Cannot Delete",
                "Cannot delete the only page in the document.",
            )
            return
        reply = QMessageBox.question(
            self,
            "Delete Page",
            f"Delete page {idx + 1}? This cannot be undone (close without saving to revert).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_page_op(
            "Delete Page",
            lambda: self._active_tab.delete_pages([idx]),
        )

    def _on_insert_blank(self) -> None:
        idx = self._current_page_index()
        if idx is None:
            return
        info = self._active_tab.adapter.get_page_info(idx)
        self._run_page_op(
            "Insert Blank Page",
            lambda: self._active_tab.insert_blank_page(
                idx + 1, info.width_points, info.height_points
            ),
        )

    def _on_duplicate_page(self) -> None:
        idx = self._current_page_index()
        if idx is None:
            return
        self._run_page_op(
            "Duplicate Page",
            lambda: self._active_tab.duplicate_page(idx),
        )

    def _on_move_page(self) -> None:
        idx = self._current_page_index()
        if idx is None:
            return
        n = self._active_tab.page_view.page_count
        if n < 2:
            QMessageBox.information(
                self,
                "Move Page",
                "Move requires at least 2 pages.",
            )
            return
        target, ok = QInputDialog.getInt(
            self,
            "Move Page",
            f"Move page {idx + 1} to position (1-{n}):",
            value=idx + 1,
            minValue=1,
            maxValue=n,
        )
        if not ok:
            return
        new_idx = target - 1
        if new_idx == idx:
            return
        self._run_page_op(
            "Move Page",
            lambda: self._active_tab.move_page(idx, new_idx),
        )

    def _on_crop_page(self) -> None:
        idx = self._current_page_index()
        if idx is None:
            return
        info = self._active_tab.adapter.get_page_info(idx)
        dlg = CropDialog(
            page_index=idx,
            page_width=info.width_points,
            page_height=info.height_points,
            page_cache=self._active_tab.organize_panel.cache,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        margins = dlg.margins
        self._run_page_op(
            "Crop Page",
            lambda: self._active_tab.crop_page(idx, margins),
        )

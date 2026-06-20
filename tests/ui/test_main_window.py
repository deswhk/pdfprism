"""Tests for MainWindow tab management."""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox

from pdfprism.services.search import SearchScope
from pdfprism.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def _isolate_qsettings(tmp_path: Path):
    """Redirect QSettings to a per-test temp directory so tests do not
    pollute the user's real recent-files / dark-mode / last-dir state."""
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    yield


@pytest.fixture
def main_window(qtbot) -> MainWindow:
    mw = MainWindow()
    qtbot.addWidget(mw)
    return mw


@pytest.fixture
def silent_critical(monkeypatch):
    """Patch QMessageBox.critical so failure-path tests do not block on a modal."""
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: 0)


class TestEmptyState:
    def test_starts_empty(self, main_window: MainWindow) -> None:
        assert main_window._active_tab is None
        assert main_window._tab_widget.count() == 0
        assert main_window._stacked_central.currentIndex() == 0


class TestOpen:
    def test_open_creates_active_tab(self, main_window: MainWindow, sample_pdf_path: Path) -> None:
        main_window._open_path(sample_pdf_path)
        assert main_window._tab_widget.count() == 1
        assert main_window._active_tab is not None
        assert main_window._active_tab.path == sample_pdf_path.resolve(strict=False)

    def test_open_second_creates_second_tab(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        main_window._open_path(sample_pdf_path)
        assert main_window._tab_widget.count() == 2

    def test_open_failure_creates_no_tab(
        self,
        main_window: MainWindow,
        garbage_file: Path,
        silent_critical: None,
    ) -> None:
        main_window._open_path(garbage_file)
        assert main_window._tab_widget.count() == 0
        assert main_window._active_tab is None


class TestClose:
    def test_close_active_tab_keeps_other(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        main_window._open_path(sample_pdf_path)
        main_window._on_close_tab()
        assert main_window._tab_widget.count() == 1
        assert main_window._active_tab is not None

    def test_close_last_tab_enters_empty_state(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        main_window._on_close_tab()
        assert main_window._active_tab is None
        assert main_window._tab_widget.count() == 0
        assert main_window._stacked_central.currentIndex() == 0


class TestSwitching:
    def test_switch_changes_active_tab(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        first_tab = main_window._active_tab
        main_window._open_path(sample_pdf_path)
        second_tab = main_window._active_tab
        assert first_tab is not second_tab
        main_window._tab_widget.setCurrentIndex(0)
        assert main_window._active_tab is first_tab

    def test_next_tab_wraps(self, main_window: MainWindow, sample_pdf_path: Path) -> None:
        main_window._open_path(sample_pdf_path)
        main_window._open_path(sample_pdf_path)
        main_window._tab_widget.setCurrentIndex(0)
        main_window._on_next_tab()
        assert main_window._tab_widget.currentIndex() == 1
        main_window._on_next_tab()
        assert main_window._tab_widget.currentIndex() == 0  # wraps

    def test_prev_tab_wraps(self, main_window: MainWindow, sample_pdf_path: Path) -> None:
        main_window._open_path(sample_pdf_path)
        main_window._open_path(sample_pdf_path)
        main_window._tab_widget.setCurrentIndex(1)
        main_window._on_prev_tab()
        assert main_window._tab_widget.currentIndex() == 0
        main_window._on_prev_tab()
        assert main_window._tab_widget.currentIndex() == 1  # wraps


class TestSidebarBinding:
    def test_active_tab_panels_shown(self, main_window: MainWindow, sample_pdf_path: Path) -> None:
        main_window._open_path(sample_pdf_path)
        active = main_window._active_tab
        assert main_window._thumbnail_stack.currentWidget() is active.thumbnail_panel
        assert main_window._outline_stack.currentWidget() is active.outline_panel

    def test_sidebars_swap_on_tab_switch(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        first_tab = main_window._active_tab
        main_window._open_path(sample_pdf_path)
        assert (
            main_window._thumbnail_stack.currentWidget() is main_window._active_tab.thumbnail_panel
        )
        main_window._tab_widget.setCurrentIndex(0)
        assert main_window._thumbnail_stack.currentWidget() is first_tab.thumbnail_panel


class TestCrossSearch:
    @staticmethod
    def _enter_all_open(main_window: MainWindow) -> None:
        combo = main_window._search_bar._scope_combo
        combo.setCurrentIndex(combo.findData(SearchScope.ALL_OPEN))

    def test_all_open_scope_searches_every_tab(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        main_window._open_path(sample_pdf_path)
        self._enter_all_open(main_window)
        main_window._on_find("Page")
        counter_text = main_window._search_bar._counter_label.text()
        assert "in 2 docs" in counter_text

    def test_cross_search_shows_results_dock(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        main_window._open_path(sample_pdf_path)
        self._enter_all_open(main_window)
        main_window._on_find("Page")
        assert not main_window._results_dock.isHidden()
        assert main_window._results_panel._tree.topLevelItemCount() == 2

    def test_first_hit_auto_selected(self, main_window: MainWindow, sample_pdf_path: Path) -> None:
        main_window._open_path(sample_pdf_path)
        main_window._open_path(sample_pdf_path)
        self._enter_all_open(main_window)
        main_window._on_find("Page")
        assert main_window._cross_search_index == 0

    def test_find_next_advances_cursor(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        main_window._open_path(sample_pdf_path)
        self._enter_all_open(main_window)
        main_window._on_find("Page")
        main_window._on_find_next()
        assert main_window._cross_search_index == 1

    def test_find_next_wraps(self, main_window: MainWindow, sample_pdf_path: Path) -> None:
        main_window._open_path(sample_pdf_path)
        self._enter_all_open(main_window)
        main_window._on_find("Page")
        total = len(main_window._cross_search_results)
        assert total > 0
        for _ in range(total):
            main_window._on_find_next()
        assert main_window._cross_search_index == 0

    def test_find_next_across_doc_boundary_preserves_state(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        main_window._open_path(sample_pdf_path)
        self._enter_all_open(main_window)
        main_window._on_open_search()
        main_window._on_find("Page")
        # Advance until the cursor is at the first hit in doc 1.
        target = next(
            i for i, r in enumerate(main_window._cross_search_results) if r.doc_index == 1
        )
        while main_window._cross_search_index < target:
            main_window._on_find_next()
        # Crossing the doc boundary must not drop cross-search state.
        assert main_window._cross_search_results != []
        assert main_window._cross_search_index == target
        assert main_window._tab_widget.currentIndex() == 1

    def test_find_prev_wraps_from_zero(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        self._enter_all_open(main_window)
        main_window._on_find("Page")
        last = len(main_window._cross_search_results) - 1
        main_window._on_find_prev()
        assert main_window._cross_search_index == last

    def test_clicking_result_jumps_to_tab(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        main_window._open_path(sample_pdf_path)
        self._enter_all_open(main_window)
        main_window._on_find("Page")
        # Find an index that lives in tab 1 (doc_index 1)
        target = next(
            i for i, r in enumerate(main_window._cross_search_results) if r.doc_index == 1
        )
        main_window._tab_widget.setCurrentIndex(0)
        main_window._on_result_selected(target)
        assert main_window._tab_widget.currentIndex() == 1
        assert main_window._cross_search_index == target

    def test_close_search_hides_results_dock(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        self._enter_all_open(main_window)
        main_window._on_find("Page")
        assert not main_window._results_dock.isHidden()
        main_window._on_close_search()
        assert main_window._results_dock.isHidden()
        assert main_window._cross_search_results == []

    def test_single_doc_search_hides_results_dock(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        self._enter_all_open(main_window)
        main_window._on_find("Page")
        assert not main_window._results_dock.isHidden()
        combo = main_window._search_bar._scope_combo
        combo.setCurrentIndex(combo.findData(SearchScope.CURRENT))
        main_window._on_find("Page")
        assert main_window._results_dock.isHidden()
        assert main_window._cross_search_results == []

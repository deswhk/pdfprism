"""Tests for MainWindow tab management."""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from pdfprism.services.search import SearchScope
from pdfprism.ui.main_window import MainWindow
from pdfprism.ui.widgets.page_view import ToolMode


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


class TestSearchToggles:
    """Toggles in SearchBar reach the service in both find paths."""

    @staticmethod
    def _set_case(main_window: MainWindow, on: bool) -> None:
        main_window._search_bar._case_btn.setChecked(on)

    @staticmethod
    def _set_whole(main_window: MainWindow, on: bool) -> None:
        main_window._search_bar._whole_btn.setChecked(on)

    def test_case_sensitive_single_doc_no_match(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        self._set_case(main_window, True)
        main_window._on_find("page")  # lowercase, fixture has only "Page"
        assert main_window._active_tab.search_hits == []

    def test_case_sensitive_single_doc_finds_capitalized(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        self._set_case(main_window, True)
        main_window._on_find("Page")
        assert len(main_window._active_tab.search_hits) >= 1

    def test_whole_word_single_doc_rejects_substring(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        self._set_whole(main_window, True)
        main_window._on_find("pdf")  # substring of "pdfprism"
        assert main_window._active_tab.search_hits == []

    def test_default_substring_finds_pdf(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        """No toggles: pdf-as-substring still matches inside pdfprism."""
        main_window._open_path(sample_pdf_path)
        main_window._on_find("pdf")
        assert len(main_window._active_tab.search_hits) >= 1

    def test_case_sensitive_cross_doc(self, main_window: MainWindow, sample_pdf_path: Path) -> None:
        """Toggles flow through find_all_across as well."""
        main_window._open_path(sample_pdf_path)
        main_window._open_path(sample_pdf_path)
        TestCrossSearch._enter_all_open(main_window)
        self._set_case(main_window, True)
        main_window._on_find("page")  # lowercase
        assert main_window._cross_search_results == []

    def test_case_sensitive_cross_doc_finds_capitalized(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        main_window._open_path(sample_pdf_path)
        TestCrossSearch._enter_all_open(main_window)
        self._set_case(main_window, True)
        main_window._on_find("Page")
        assert len(main_window._cross_search_results) >= 2
        assert {h.doc_index for h in main_window._cross_search_results} == {0, 1}


class TestCopy:
    def test_copy_with_no_active_tab_is_noop(self, main_window: MainWindow) -> None:
        # Should not raise; should not write anything to clipboard either.
        main_window._on_copy()

    def test_copy_with_no_selection_is_noop(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        clipboard = QApplication.clipboard()
        clipboard.clear()
        main_window._on_copy()
        # Empty selection -> clipboard remains empty.
        assert clipboard.text() == ""

    def test_copy_with_selection_writes_to_clipboard(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        from PySide6.QtCore import QPointF

        main_window._open_path(sample_pdf_path)
        tab = main_window._active_tab
        assert tab is not None
        tab.page_view.set_tool_mode(ToolMode.SELECT)
        words = tab.adapter.extract_words(0)
        hello = next(w for w in words if w.text == "Hello")
        render_scale = 2.0
        tab.page_view._update_selection_from_drag(
            QPointF((hello.x0 - 1) * render_scale, (hello.y0 - 1) * render_scale),
            QPointF((hello.x1 + 1) * render_scale, (hello.y1 + 1) * render_scale),
        )
        clipboard = QApplication.clipboard()
        clipboard.clear()
        main_window._on_copy()
        assert clipboard.text() == "Hello"


class TestContextMenuSignalsWired:
    def test_copy_signal_triggers_copy(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        from PySide6.QtCore import QPointF

        main_window._open_path(sample_pdf_path)
        tab = main_window._active_tab
        assert tab is not None
        tab.page_view.set_tool_mode(ToolMode.SELECT)
        words = tab.adapter.extract_words(0)
        hello = next(w for w in words if w.text == "Hello")
        render_scale = 2.0
        tab.page_view._update_selection_from_drag(
            QPointF((hello.x0 - 1) * render_scale, (hello.y0 - 1) * render_scale),
            QPointF((hello.x1 + 1) * render_scale, (hello.y1 + 1) * render_scale),
        )
        clipboard = QApplication.clipboard()
        clipboard.clear()
        tab.page_view.copy_requested.emit()
        assert clipboard.text() == "Hello"

    def test_extract_selection_signal_writes_file(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtWidgets import QFileDialog

        out_file = tmp_path / "selection.txt"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *a, **kw: (str(out_file), ""),
        )
        main_window._open_path(sample_pdf_path)
        tab = main_window._active_tab
        assert tab is not None
        tab.page_view.set_tool_mode(ToolMode.SELECT)
        words = tab.adapter.extract_words(0)
        hello = next(w for w in words if w.text == "Hello")
        render_scale = 2.0
        tab.page_view._update_selection_from_drag(
            QPointF((hello.x0 - 1) * render_scale, (hello.y0 - 1) * render_scale),
            QPointF((hello.x1 + 1) * render_scale, (hello.y1 + 1) * render_scale),
        )
        tab.page_view.extract_selection_requested.emit()
        assert out_file.exists()
        assert out_file.read_text(encoding="utf-8") == "Hello"


class TestExtractMenu:
    def test_extract_text_no_active_tab_is_noop(self, main_window: MainWindow) -> None:
        main_window._on_extract_text()
        assert main_window._active_tab is None

    def test_extract_text_writes_all_pages(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from PySide6.QtWidgets import QDialog, QFileDialog

        out_file = tmp_path / "all.txt"
        monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *a, **kw: (str(out_file), ""),
        )
        main_window._open_path(sample_pdf_path)
        main_window._on_extract_text()
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert content.count("\f") == 2
        assert "Page 1" in content
        assert "Page 3" in content

    def test_extract_images_text_only_pdf_reports_zero(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from PySide6.QtWidgets import QDialog, QFileDialog

        out_dir = tmp_path / "imgs"
        out_dir.mkdir()
        monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
        monkeypatch.setattr(
            QFileDialog,
            "getExistingDirectory",
            lambda *a, **kw: str(out_dir),
        )
        info_called = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: info_called.append(a))
        main_window._open_path(sample_pdf_path)
        main_window._on_extract_images()
        assert info_called
        assert list(out_dir.iterdir()) == []

    def test_extract_text_cancelled_in_dialog_writes_nothing(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from PySide6.QtWidgets import QDialog, QFileDialog

        # If the user cancels the ExtractDialog, the save-file dialog
        # should never be reached. Track whether it was called.
        save_called: list[object] = []
        monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *a, **kw: (save_called.append(1), ("", ""))[1],
        )
        main_window._open_path(sample_pdf_path)
        main_window._on_extract_text()
        assert save_called == []  # save dialog never reached


class TestToolModePersistence:
    def test_default_tool_mode_is_hand(self, main_window: MainWindow) -> None:
        assert main_window._tool_mode == ToolMode.HAND

    def test_setting_select_persists_to_qsettings(self, main_window: MainWindow) -> None:
        main_window._on_set_tool_mode(ToolMode.SELECT)
        settings = QSettings()
        stored = settings.value("tool/mode", "", type=str)
        assert stored == ToolMode.SELECT.value

    def test_changing_mode_applies_to_open_tabs(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        main_window._open_path(sample_pdf_path)
        main_window._on_set_tool_mode(ToolMode.SELECT)
        for i in range(main_window._tab_widget.count()):
            tab = main_window._tab_widget.widget(i)
            assert tab.page_view.tool_mode == ToolMode.SELECT

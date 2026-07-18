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


@pytest.fixture(autouse=True)
def _auto_discard_unsaved_prompts(monkeypatch):
    """Auto-resolve QMessageBox.question with Discard so test teardown
    does not hang on the unsaved-changes prompt that PR 8's closeEvent
    fires for modified tabs. Tests that need to assert against the
    prompt (TestCloseTabPrompt) re-monkeypatch within the test body,
    which takes precedence over this autouse default.
    """
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **kw: QMessageBox.StandardButton.Discard,
    )


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


class TestSaveActions:
    def test_save_disabled_with_no_tab(self, main_window: MainWindow) -> None:
        assert main_window.act_save.isEnabled() is False
        assert main_window.act_save_as.isEnabled() is False

    def test_save_disabled_when_clean(
        self, main_window: MainWindow, mutable_pdf_path: Path
    ) -> None:
        main_window._open_path(mutable_pdf_path)
        assert main_window.act_save.isEnabled() is False
        assert main_window.act_save_as.isEnabled() is True

    def test_save_enabled_when_dirty(self, main_window: MainWindow, mutable_pdf_path: Path) -> None:
        main_window._open_path(mutable_pdf_path)
        main_window._active_tab.rotate_page(0, 90)
        assert main_window.act_save.isEnabled() is True

    def test_save_clears_dirty(self, main_window: MainWindow, mutable_pdf_path: Path) -> None:
        main_window._open_path(mutable_pdf_path)
        main_window._active_tab.rotate_page(0, 90)
        main_window._on_save()
        assert main_window._active_tab.is_modified is False
        assert main_window.act_save.isEnabled() is False

    def test_save_as_writes_new_file(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from PySide6.QtWidgets import QFileDialog

        new_path = tmp_path / "saved.pdf"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *a, **kw: (str(new_path), ""),
        )
        main_window._open_path(mutable_pdf_path)
        main_window._active_tab.rotate_page(0, 90)
        main_window._on_save_as()
        assert new_path.exists()
        assert main_window._active_tab.path == new_path
        # Tab title updated to new filename
        assert main_window._tab_widget.tabText(0) == "saved.pdf"


class TestPageOpActions:
    def test_actions_disabled_with_no_tab(self, main_window: MainWindow) -> None:
        assert main_window.act_rotate_right.isEnabled() is False
        assert main_window.act_delete_page.isEnabled() is False
        assert main_window.act_crop_page.isEnabled() is False

    def test_actions_enabled_with_tab(
        self, main_window: MainWindow, mutable_pdf_path: Path
    ) -> None:
        main_window._open_path(mutable_pdf_path)
        assert main_window.act_rotate_right.isEnabled() is True
        assert main_window.act_delete_page.isEnabled() is True
        assert main_window.act_crop_page.isEnabled() is True

    def test_rotate_right_mutates(self, main_window: MainWindow, mutable_pdf_path: Path) -> None:
        main_window._open_path(mutable_pdf_path)
        before = main_window._active_tab.adapter.get_page_info(0).rotation
        main_window._on_rotate_right()
        after = main_window._active_tab.adapter.get_page_info(0).rotation
        assert (after - before) % 360 == 90

    def test_duplicate_increments_pages(
        self, main_window: MainWindow, mutable_pdf_path: Path
    ) -> None:
        main_window._open_path(mutable_pdf_path)
        before = main_window._active_tab.page_view.page_count
        main_window._on_duplicate_page()
        assert main_window._active_tab.page_view.page_count == before + 1

    def test_insert_blank_increments_pages(
        self, main_window: MainWindow, mutable_pdf_path: Path
    ) -> None:
        main_window._open_path(mutable_pdf_path)
        before = main_window._active_tab.page_view.page_count
        main_window._on_insert_blank()
        assert main_window._active_tab.page_view.page_count == before + 1

    def test_delete_page_with_confirm(
        self, main_window: MainWindow, mutable_pdf_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *a, **kw: QMessageBox.StandardButton.Yes,
        )
        main_window._open_path(mutable_pdf_path)
        before = main_window._active_tab.page_view.page_count
        main_window._on_delete_page()
        assert main_window._active_tab.page_view.page_count == before - 1

    def test_delete_page_declined_keeps_pages(
        self, main_window: MainWindow, mutable_pdf_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *a, **kw: QMessageBox.StandardButton.No,
        )
        main_window._open_path(mutable_pdf_path)
        before = main_window._active_tab.page_view.page_count
        main_window._on_delete_page()
        assert main_window._active_tab.page_view.page_count == before

    def test_move_page_via_dialog(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
        monkeypatch,
    ) -> None:
        from PySide6.QtWidgets import QInputDialog

        main_window._open_path(mutable_pdf_path)
        # Move page 1 to position 3 (1-based)
        monkeypatch.setattr(
            QInputDialog,
            "getInt",
            lambda *a, **kw: (3, True),
        )
        t0 = main_window._active_tab.adapter.extract_text(0)
        main_window._on_move_page()
        # After move, P0's text should be at index 2 (3 - 1)
        assert main_window._active_tab.adapter.extract_text(2) == t0


class TestModifiedTabTitle:
    def test_title_shows_star_when_modified(
        self, main_window: MainWindow, mutable_pdf_path: Path
    ) -> None:
        main_window._open_path(mutable_pdf_path)
        main_window._active_tab.rotate_page(0, 90)
        assert main_window._tab_widget.tabText(0) == "mutable.pdf *"

    def test_title_drops_star_after_save(
        self, main_window: MainWindow, mutable_pdf_path: Path
    ) -> None:
        main_window._open_path(mutable_pdf_path)
        main_window._active_tab.rotate_page(0, 90)
        main_window._on_save()
        assert main_window._tab_widget.tabText(0) == "mutable.pdf"


class TestCloseTabPrompt:
    def test_close_clean_tab_no_prompt(
        self, main_window: MainWindow, mutable_pdf_path: Path, monkeypatch
    ) -> None:
        # If we call this and the prompt fires unexpectedly, the test will
        # hang on the modal. So we install a sentinel that records the call.
        prompted: list[object] = []
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *a, **kw: (prompted.append(1), QMessageBox.StandardButton.Cancel)[1],
        )
        main_window._open_path(mutable_pdf_path)
        main_window._on_close_tab()
        assert prompted == []  # never prompted for clean tab
        assert main_window._tab_widget.count() == 0

    def test_cancel_keeps_tab(
        self, main_window: MainWindow, mutable_pdf_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *a, **kw: QMessageBox.StandardButton.Cancel,
        )
        main_window._open_path(mutable_pdf_path)
        main_window._active_tab.rotate_page(0, 90)
        main_window._on_close_tab()
        assert main_window._tab_widget.count() == 1

    def test_discard_closes_tab(
        self, main_window: MainWindow, mutable_pdf_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *a, **kw: QMessageBox.StandardButton.Discard,
        )
        main_window._open_path(mutable_pdf_path)
        main_window._active_tab.rotate_page(0, 90)
        main_window._on_close_tab()
        assert main_window._tab_widget.count() == 0

    def test_save_closes_tab_and_saves(
        self, main_window: MainWindow, mutable_pdf_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *a, **kw: QMessageBox.StandardButton.Save,
        )
        main_window._open_path(mutable_pdf_path)
        # Apply a mutation that increases page count, so we can verify the
        # saved file shows the new page count after close.
        main_window._active_tab.duplicate_page(0)
        main_window._on_close_tab()
        assert main_window._tab_widget.count() == 0
        # Reopen the file and confirm the mutation persisted.
        from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter

        verifier = PyMuPDFAdapter()
        verifier.open(mutable_pdf_path)
        try:
            assert verifier.page_count == 4
        finally:
            verifier.close()


class TestCrossDocActionEnablement:
    def test_all_disabled_empty(self, main_window: MainWindow) -> None:
        assert main_window.act_extract_pages.isEnabled() is False
        assert main_window.act_insert_pages.isEnabled() is False
        assert main_window.act_split.isEnabled() is False
        assert main_window.act_merge.isEnabled() is False

    def test_extract_insert_split_enabled_with_one_tab(
        self, main_window: MainWindow, mutable_pdf_path: Path
    ) -> None:
        main_window._open_path(mutable_pdf_path)
        assert main_window.act_extract_pages.isEnabled() is True
        assert main_window.act_insert_pages.isEnabled() is True
        assert main_window.act_split.isEnabled() is True

    def test_merge_disabled_with_one_tab(
        self, main_window: MainWindow, mutable_pdf_path: Path
    ) -> None:
        main_window._open_path(mutable_pdf_path)
        assert main_window.act_merge.isEnabled() is False

    def test_merge_enabled_with_two_tabs(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
        tmp_path: Path,
    ) -> None:
        import shutil

        second = tmp_path / "second.pdf"
        shutil.copy(mutable_pdf_path, second)
        main_window._open_path(mutable_pdf_path)
        main_window._open_path(second)
        assert main_window.act_merge.isEnabled() is True


class TestExtractPagesAction:
    def test_extract_writes_file(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from PySide6.QtWidgets import QDialog

        out = tmp_path / "extracted.pdf"

        def patch_exec(self):
            self._output_edit.setText(str(out))
            self._from_spin.setValue(1)
            self._to_spin.setValue(2)
            return QDialog.DialogCode.Accepted

        from pdfprism.ui.dialogs.extract_pages import ExtractPagesDialog

        monkeypatch.setattr(ExtractPagesDialog, "exec", patch_exec)
        main_window._open_path(mutable_pdf_path)
        main_window._on_extract_pages()
        assert out.exists()

    def test_extract_does_not_dirty_source(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from PySide6.QtWidgets import QDialog

        from pdfprism.ui.dialogs.extract_pages import ExtractPagesDialog

        out = tmp_path / "extracted.pdf"
        monkeypatch.setattr(
            ExtractPagesDialog,
            "exec",
            lambda self: (
                self._output_edit.setText(str(out)),
                QDialog.DialogCode.Accepted,
            )[1],
        )
        main_window._open_path(mutable_pdf_path)
        main_window._on_extract_pages()
        assert main_window._active_tab.is_modified is False


class TestInsertPagesAction:
    def test_cancelled_file_dialog_is_noop(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
        monkeypatch,
    ) -> None:
        from PySide6.QtWidgets import QFileDialog

        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            lambda *a, **kw: ("", ""),
        )
        main_window._open_path(mutable_pdf_path)
        before = main_window._active_tab.page_view.page_count
        main_window._on_insert_pages()
        assert main_window._active_tab.page_view.page_count == before

    def test_inserts_source_pages_and_dirties(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        import shutil

        from PySide6.QtWidgets import QDialog, QFileDialog

        source = tmp_path / "source.pdf"
        shutil.copy(mutable_pdf_path, source)

        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            lambda *a, **kw: (str(source), ""),
        )

        from pdfprism.ui.dialogs.insert_pages import InsertPagesDialog

        def patch_exec(self):
            # Default: full source range, position 1 (prepend)
            self._position_spin.setValue(1)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(InsertPagesDialog, "exec", patch_exec)
        main_window._open_path(mutable_pdf_path)
        before = main_window._active_tab.page_view.page_count
        main_window._on_insert_pages()
        # Source has 3 pages; target had 3; now 6.
        assert main_window._active_tab.page_view.page_count == before + 3
        assert main_window._active_tab.is_modified is True

    def test_invalid_source_shows_error(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        bad = tmp_path / "not_a_pdf.pdf"
        bad.write_text("this is not a PDF")

        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            lambda *a, **kw: (str(bad), ""),
        )
        errors: list[str] = []
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            lambda parent, title, msg, *a, **kw: errors.append(msg),
        )

        main_window._open_path(mutable_pdf_path)
        main_window._on_insert_pages()
        assert any("Cannot open" in e for e in errors)


class TestSplitAction:
    def test_split_writes_files(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from PySide6.QtWidgets import QMessageBox

        out_dir = tmp_path / "split_out"
        out_dir.mkdir()

        monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: 0)

        from pdfprism.ui.dialogs.split import SplitDialog

        def patch_exec(self):
            self._dir_edit.setText(str(out_dir))
            self._every_spin.setValue(1)  # one PDF per page
            self._on_accept()
            return self.result()

        monkeypatch.setattr(SplitDialog, "exec", patch_exec)
        main_window._open_path(mutable_pdf_path)
        main_window._on_split()
        # mutable_pdf_path is the 3-page sample
        files = sorted(out_dir.glob("*.pdf"))
        assert len(files) == 3

    def test_split_does_not_dirty_source(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from PySide6.QtWidgets import QMessageBox

        out_dir = tmp_path / "split_out"
        out_dir.mkdir()
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: 0)

        from pdfprism.ui.dialogs.split import SplitDialog

        def patch_exec(self):
            self._dir_edit.setText(str(out_dir))
            self._every_spin.setValue(2)
            self._on_accept()
            return self.result()

        monkeypatch.setattr(SplitDialog, "exec", patch_exec)
        main_window._open_path(mutable_pdf_path)
        main_window._on_split()
        assert main_window._active_tab.is_modified is False


class TestMergeAction:
    def test_merge_with_one_tab_is_noop(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
    ) -> None:
        main_window._open_path(mutable_pdf_path)
        before = main_window._tab_widget.count()
        main_window._on_merge()
        # Nothing happens; no new tab.
        assert main_window._tab_widget.count() == before

    def test_merge_writes_file_and_opens_new_tab(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        import shutil

        from PySide6.QtWidgets import QDialog

        second = tmp_path / "second.pdf"
        shutil.copy(mutable_pdf_path, second)
        merged = tmp_path / "merged.pdf"

        from pdfprism.ui.dialogs.merge import MergeDialog

        def patch_exec(self):
            self._output_edit.setText(str(merged))
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(MergeDialog, "exec", patch_exec)

        main_window._open_path(mutable_pdf_path)
        main_window._open_path(second)
        main_window._on_merge()
        assert merged.exists()
        # Merged file should be opened as a new tab (3rd one).
        assert main_window._tab_widget.count() == 3

    def test_merge_does_not_dirty_sources(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        import shutil

        from PySide6.QtWidgets import QDialog

        second = tmp_path / "second.pdf"
        shutil.copy(mutable_pdf_path, second)
        merged = tmp_path / "merged.pdf"

        from pdfprism.ui.dialogs.merge import MergeDialog

        monkeypatch.setattr(
            MergeDialog,
            "exec",
            lambda self: (
                self._output_edit.setText(str(merged)),
                QDialog.DialogCode.Accepted,
            )[1],
        )

        main_window._open_path(mutable_pdf_path)
        main_window._open_path(second)
        main_window._on_merge()
        # First two tabs (sources) remain clean.
        assert main_window._tab_widget.widget(0).is_modified is False
        assert main_window._tab_widget.widget(1).is_modified is False


class TestOrganizeDock:
    def test_dock_hidden_by_default(self, main_window: MainWindow) -> None:
        assert main_window._organize_dock.isVisible() is False

    def test_toggle_shortcut_is_f6(self, main_window: MainWindow) -> None:
        from PySide6.QtGui import QKeySequence

        assert main_window.act_toggle_organize.shortcut() == QKeySequence("F6")

    def test_toggle_shows_dock(self, main_window: MainWindow) -> None:
        main_window.show()
        main_window.act_toggle_organize.trigger()
        assert main_window._organize_dock.isVisible() is True

    def test_organize_action_in_view_menu(self, main_window: MainWindow) -> None:
        # The act_toggle_organize action should belong to the View menu.
        menubar = main_window.menuBar()
        for ma in menubar.actions():
            if "View" not in ma.text():
                continue
            view_menu = ma.menu()
            assert main_window.act_toggle_organize in view_menu.actions()
            return
        raise AssertionError("View menu not found")


class TestOrganizePanelPerTabSwap:
    def test_active_tabs_organize_panel_in_stack(
        self, main_window: MainWindow, mutable_pdf_path: Path
    ) -> None:
        main_window._open_path(mutable_pdf_path)
        active = main_window._active_tab
        assert main_window._organize_stack.currentWidget() is active.organize_panel

    def test_switching_tabs_swaps_organize_panel(
        self, main_window: MainWindow, mutable_pdf_path: Path, tmp_path: Path
    ) -> None:
        import shutil

        second = tmp_path / "second.pdf"
        shutil.copy(mutable_pdf_path, second)

        main_window._open_path(mutable_pdf_path)
        main_window._open_path(second)
        # Active tab is now the second one
        second_tab = main_window._active_tab
        assert main_window._organize_stack.currentWidget() is second_tab.organize_panel

        # Switch back to first tab
        main_window._tab_widget.setCurrentIndex(0)
        first_tab = main_window._tab_widget.widget(0)
        assert main_window._organize_stack.currentWidget() is first_tab.organize_panel

    def test_closing_last_tab_resets_stack(
        self, main_window: MainWindow, mutable_pdf_path: Path
    ) -> None:
        main_window._open_path(mutable_pdf_path)
        # Close the only tab via the tab-close signal.
        main_window._on_tab_close_requested(0)
        # Stack should be back to the placeholder (index 0)
        assert main_window._organize_stack.currentIndex() == 0


# ---- PR 9.5: MainWindow selection actions --------------------------------


class TestOrganizeSelectionActionsExist:
    """Both actions and menu entries are wired at MainWindow level."""

    def test_act_crop_selection_defined(self, main_window: MainWindow) -> None:
        """Positive: action exists and has the expected label."""
        assert hasattr(main_window, "act_crop_selection")
        assert main_window.act_crop_selection.text() == "Crop &Selection..."

    def test_act_extract_selection_defined(self, main_window: MainWindow) -> None:
        """Positive: action exists and has the expected label."""
        assert hasattr(main_window, "act_extract_selection")
        assert main_window.act_extract_selection.text() == "Extract Selectio&n..."


class TestOrganizeSelectionActionsDisabledInitially:
    """Negative: no tab open -> actions disabled."""

    def test_crop_selection_disabled_empty_state(self, main_window: MainWindow) -> None:
        assert main_window.act_crop_selection.isEnabled() is False

    def test_extract_selection_disabled_empty_state(self, main_window: MainWindow) -> None:
        assert main_window.act_extract_selection.isEnabled() is False


class TestOrganizeSelectionEnabledOnSelection:
    """Positive: actions enable when the active tab has a selection."""

    def test_crop_enabled_after_selection(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        """End-to-end: open, select a page, action becomes enabled."""
        main_window._open_path(sample_pdf_path)
        assert main_window.act_crop_selection.isEnabled() is False  # no selection yet
        # Select page 0 in the active tab's organize panel grid
        panel = main_window._active_tab.organize_panel
        panel._grid.setCurrentIndex(panel._grid._model.index(0, 0))
        assert main_window.act_crop_selection.isEnabled() is True

    def test_extract_enabled_after_selection(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        assert main_window.act_extract_selection.isEnabled() is False
        panel = main_window._active_tab.organize_panel
        panel._grid.setCurrentIndex(panel._grid._model.index(1, 0))
        assert main_window.act_extract_selection.isEnabled() is True


class TestOrganizeSelectionActionsDisabledWithoutSelection:
    """Negative: tab open but no selection -> actions still disabled."""

    def test_crop_stays_disabled_no_selection(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        # Deliberately do not select anything.
        assert main_window.act_crop_selection.isEnabled() is False

    def test_extract_stays_disabled_no_selection(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        main_window._open_path(sample_pdf_path)
        assert main_window.act_extract_selection.isEnabled() is False


class TestOrganizeSelectionSlots:
    """Slots delegate to the active tab's OrganizePagesPanel."""

    def test_crop_slot_delegates_to_panel(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: MainWindow's slot calls panel._on_crop_requested."""
        main_window._open_path(sample_pdf_path)
        panel = main_window._active_tab.organize_panel
        # Select something so the panel wouldn't early-return on
        # selected_indices; but the slot delegation itself is what we
        # test, so we spy on the panel method.
        panel._grid.setCurrentIndex(panel._grid._model.index(0, 0))
        called: list = []
        monkeypatch.setattr(
            panel,
            "_on_crop_requested",
            lambda: called.append(True),
        )
        main_window._on_organize_crop_selection()
        assert called == [True]

    def test_extract_slot_delegates_to_panel(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: MainWindow's slot calls panel._on_extract_requested."""
        main_window._open_path(sample_pdf_path)
        panel = main_window._active_tab.organize_panel
        panel._grid.setCurrentIndex(panel._grid._model.index(0, 0))
        called: list = []
        monkeypatch.setattr(
            panel,
            "_on_extract_requested",
            lambda: called.append(True),
        )
        main_window._on_organize_extract_selection()
        assert called == [True]

    def test_crop_slot_no_active_tab_is_noop(self, main_window: MainWindow) -> None:
        """Negative: no active tab -> slot returns without raising."""
        assert main_window._active_tab is None
        main_window._on_organize_crop_selection()  # must not raise

    def test_extract_slot_no_active_tab_is_noop(self, main_window: MainWindow) -> None:
        """Negative: no active tab -> slot returns without raising."""
        assert main_window._active_tab is None
        main_window._on_organize_extract_selection()  # must not raise


class TestOrganizeSelectionMenuEntries:
    """Menu discoverability: both actions live in the right menus.

    Uses findChildren(QMenu) to enumerate menus by title() rather than
    iterating menuBar().actions() and calling .text() on each -- the
    latter is fragile because separator QActions can be reaped by
    shiboken between the outer-loop and inner-loop, raising
    ``libshiboken: Internal C++ object already deleted``. Matching by
    QMenu.title() sidesteps that entirely.
    """

    @staticmethod
    def _find_menu_by_title(main_window: MainWindow, title: str):
        """Return the first QMenu on ``main_window`` whose title matches."""
        from PySide6.QtWidgets import QMenu

        for menu in main_window.findChildren(QMenu):
            if menu.title() == title:
                return menu
        return None

    def test_crop_selection_in_edit_page_menu(self, main_window: MainWindow) -> None:
        """Positive: Edit -> Page menu contains act_crop_selection."""
        page_menu = self._find_menu_by_title(main_window, "&Page")
        assert page_menu is not None
        assert main_window.act_crop_selection in page_menu.actions()

    def test_extract_selection_in_file_pages_menu(self, main_window: MainWindow) -> None:
        """Positive: File -> Pages menu contains act_extract_selection."""
        pages_menu = self._find_menu_by_title(main_window, "&Pages")
        assert pages_menu is not None
        assert main_window.act_extract_selection in pages_menu.actions()


# ---- PR 10: encrypted PDF open flow ---------------------------------


class _PasswordDialogStub:
    """Stub for PasswordDialog that scripts a sequence of user actions.

    Constructed with a list of ``(exec_result, password)`` tuples that
    are consumed in order. ``exec_result`` is Accepted or Rejected;
    ``password`` is the string ``self.password`` should return for that
    attempt.
    """

    def __init__(self, script: list[tuple[int, str]]):
        self._script = script
        self._call_count = 0
        self.errors_seen: list[str | None] = []

    def make_class(self):
        """Return a class that mimics PasswordDialog but reads from script."""
        stub_self = self

        class _StubDialog:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def exec(self):
                idx = stub_self._call_count
                stub_self._call_count += 1
                if idx >= len(stub_self._script):
                    raise AssertionError(
                        f"PasswordDialog.exec called {idx + 1} times "
                        f"but script has only {len(stub_self._script)} entries"
                    )
                stub_self._last_exec_idx = idx
                return stub_self._script[idx][0]

            @property
            def password(self) -> str:
                return stub_self._script[stub_self._last_exec_idx][1]

            def set_error_message(self, msg) -> None:
                stub_self.errors_seen.append(msg)

        return _StubDialog


class TestOpenEncryptedPdfHappyPath:
    """Encrypted PDF flows that end in a successfully opened tab."""

    def test_correct_password_first_try_opens_tab(
        self,
        main_window: MainWindow,
        encrypted_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: right password on first attempt -> tab opens."""
        from PySide6.QtWidgets import QDialog

        from pdfprism.ui.dialogs import password as password_mod
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        script = _PasswordDialogStub([(QDialog.DialogCode.Accepted, ENCRYPTED_PDF_PASSWORD)])
        monkeypatch.setattr(password_mod, "PasswordDialog", script.make_class())
        # Also patch the import used by main_window.
        from pdfprism.ui import main_window as mw_mod

        monkeypatch.setattr(mw_mod, "PasswordDialog", script.make_class())

        main_window._open_path(encrypted_pdf_path)
        assert main_window._tab_widget.count() == 1
        assert main_window._active_tab is not None
        assert script.errors_seen == []  # no wrong-password errors shown

    def test_wrong_then_correct_password_opens_tab(
        self,
        main_window: MainWindow,
        encrypted_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive (retry loop): wrong then right -> tab opens; error banner shown once."""
        from PySide6.QtWidgets import QDialog

        from pdfprism.ui import main_window as mw_mod
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        script = _PasswordDialogStub(
            [
                (QDialog.DialogCode.Accepted, "wrong"),
                (QDialog.DialogCode.Accepted, ENCRYPTED_PDF_PASSWORD),
            ]
        )
        monkeypatch.setattr(mw_mod, "PasswordDialog", script.make_class())

        main_window._open_path(encrypted_pdf_path)
        assert main_window._tab_widget.count() == 1
        assert main_window._active_tab is not None
        # Exactly one error banner from the wrong-password attempt.
        assert len(script.errors_seen) == 1
        assert script.errors_seen[0] and "Incorrect" in script.errors_seen[0]

    def test_multiple_wrong_then_correct_opens_tab(
        self,
        main_window: MainWindow,
        encrypted_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: 3 wrong then 1 correct -> tab opens (unlimited retries)."""
        from PySide6.QtWidgets import QDialog

        from pdfprism.ui import main_window as mw_mod
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        script = _PasswordDialogStub(
            [
                (QDialog.DialogCode.Accepted, "wrong1"),
                (QDialog.DialogCode.Accepted, "wrong2"),
                (QDialog.DialogCode.Accepted, "wrong3"),
                (QDialog.DialogCode.Accepted, ENCRYPTED_PDF_PASSWORD),
            ]
        )
        monkeypatch.setattr(mw_mod, "PasswordDialog", script.make_class())

        main_window._open_path(encrypted_pdf_path)
        assert main_window._tab_widget.count() == 1
        assert len(script.errors_seen) == 3


class TestOpenEncryptedPdfCancelPath:
    """Encrypted PDF flows that end in no tab (user cancelled)."""

    def test_immediate_cancel_produces_empty_state(
        self,
        main_window: MainWindow,
        encrypted_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Negative: Cancel on first prompt -> no tab, no active_tab."""
        from PySide6.QtWidgets import QDialog

        from pdfprism.ui import main_window as mw_mod

        script = _PasswordDialogStub([(QDialog.DialogCode.Rejected, "")])
        monkeypatch.setattr(mw_mod, "PasswordDialog", script.make_class())

        main_window._open_path(encrypted_pdf_path)
        assert main_window._tab_widget.count() == 0
        assert main_window._active_tab is None

    def test_wrong_then_cancel_produces_empty_state(
        self,
        main_window: MainWindow,
        encrypted_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Negative: wrong password, then Cancel -> no tab."""
        from PySide6.QtWidgets import QDialog

        from pdfprism.ui import main_window as mw_mod

        script = _PasswordDialogStub(
            [
                (QDialog.DialogCode.Accepted, "wrong"),
                (QDialog.DialogCode.Rejected, ""),
            ]
        )
        monkeypatch.setattr(mw_mod, "PasswordDialog", script.make_class())

        main_window._open_path(encrypted_pdf_path)
        assert main_window._tab_widget.count() == 0
        # But the wrong attempt did trigger an error banner before Cancel.
        assert len(script.errors_seen) == 1


class TestOpenPreservesUnencryptedPath:
    """Regression: unencrypted PDF path must not touch the prompt code."""

    def test_unencrypted_open_does_not_construct_password_dialog(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Negative regression: opening an unencrypted PDF must not
        construct PasswordDialog at all -- would indicate a wiring bug."""
        from pdfprism.ui import main_window as mw_mod

        constructed: list = []

        class _ExplodeDialog:
            def __init__(self, *a, **kw) -> None:
                constructed.append(True)
                raise AssertionError("PasswordDialog was constructed on an unencrypted PDF open")

        monkeypatch.setattr(mw_mod, "PasswordDialog", _ExplodeDialog)

        main_window._open_path(sample_pdf_path)
        assert main_window._tab_widget.count() == 1
        assert constructed == []


class TestOpenNonPasswordFailurePath:
    """Non-password failures still take the flat error dialog path."""

    def test_garbage_file_shows_error_no_password_prompt(
        self,
        main_window: MainWindow,
        garbage_file: Path,
        monkeypatch,
    ) -> None:
        """Negative: not-a-PDF failure surfaces a critical dialog and
        never constructs PasswordDialog."""
        from PySide6.QtWidgets import QMessageBox

        from pdfprism.ui import main_window as mw_mod

        constructed: list = []

        class _ExplodeDialog:
            def __init__(self, *a, **kw) -> None:
                constructed.append(True)
                raise AssertionError("PasswordDialog constructed on a non-password failure")

        monkeypatch.setattr(mw_mod, "PasswordDialog", _ExplodeDialog)
        # Silence the critical dialog so the test doesn't block.
        monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: 0)

        main_window._open_path(garbage_file)
        assert main_window._tab_widget.count() == 0
        assert constructed == []

    def test_missing_file_shows_error_no_password_prompt(
        self,
        main_window: MainWindow,
        missing_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Negative: missing file surfaces critical dialog, no password prompt."""
        from PySide6.QtWidgets import QMessageBox

        from pdfprism.ui import main_window as mw_mod

        constructed: list = []
        monkeypatch.setattr(
            mw_mod,
            "PasswordDialog",
            lambda *a, **k: constructed.append(True) or (_ for _ in ()).throw(AssertionError()),
        )
        monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: 0)

        main_window._open_path(missing_pdf_path)
        assert main_window._tab_widget.count() == 0
        assert constructed == []


# ---- PR 10.5: File -> Security -> Password -------------------------------


class _CryptDialogStub:
    """Stub for CryptDialog: preprogrammed exec result + password/remove state."""

    def __init__(
        self,
        exec_result: int,
        new_password: str = "",
        remove_requested: bool = False,
    ):
        self._exec_result = exec_result
        self._new_password = new_password
        self._remove_requested = remove_requested
        self.constructed_with: tuple | None = None

    def make_class(self):
        stub_self = self

        class _StubDialog:
            def __init__(self, is_encrypted, filename, parent=None):
                stub_self.constructed_with = (is_encrypted, filename)

            def exec(self):
                return stub_self._exec_result

            @property
            def new_password(self):
                return stub_self._new_password

            @property
            def remove_requested(self):
                return stub_self._remove_requested

        return _StubDialog


class TestSecurityPasswordAction:
    """The File -> Security -> Password... action's existence and menu placement."""

    def test_action_exists(self, main_window: MainWindow) -> None:
        assert hasattr(main_window, "act_security_password")
        assert main_window.act_security_password.text() == "&Password..."

    def test_action_disabled_empty_state(self, main_window: MainWindow) -> None:
        """Negative: no tab open -> action disabled."""
        assert main_window.act_security_password.isEnabled() is False

    def test_action_enabled_with_unencrypted_tab(
        self, main_window: MainWindow, sample_pdf_path: Path
    ) -> None:
        """Positive: unencrypted tab open -> action enabled."""
        main_window._open_path(sample_pdf_path)
        assert main_window.act_security_password.isEnabled() is True

    def test_action_enabled_with_encrypted_tab(
        self,
        main_window: MainWindow,
        encrypted_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: encrypted tab open (post-authentication) -> enabled."""
        from PySide6.QtWidgets import QDialog

        from pdfprism.ui import main_window as mw_mod
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        # Auto-answer the password prompt so the tab opens.
        pw_script = _PasswordDialogStub([(QDialog.DialogCode.Accepted, ENCRYPTED_PDF_PASSWORD)])
        monkeypatch.setattr(mw_mod, "PasswordDialog", pw_script.make_class())

        main_window._open_path(encrypted_pdf_path)
        assert main_window.act_security_password.isEnabled() is True

    def test_action_present_in_security_menu(self, main_window: MainWindow) -> None:
        """Positive: action lives in File -> Security submenu (discoverability)."""
        # Find File menu, then Security submenu
        from PySide6.QtWidgets import QMenu

        menus = main_window.findChildren(QMenu)
        security = next((m for m in menus if m.title() == "Se&curity"), None)
        assert security is not None, "File -> Security submenu missing"
        assert main_window.act_security_password in security.actions()


class TestSecurityPasswordSlotSetPassword:
    """Slot flow: unencrypted doc + Set Password."""

    def test_accepted_dialog_calls_set_password(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: unencrypted tab + Accepted CryptDialog -> tab.set_password called."""
        from PySide6.QtWidgets import QDialog

        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(sample_pdf_path)
        stub = _CryptDialogStub(
            exec_result=QDialog.DialogCode.Accepted,
            new_password="hunter2",
            remove_requested=False,
        )
        monkeypatch.setattr(mw_mod, "CryptDialog", stub.make_class())

        called_with: list = []
        monkeypatch.setattr(
            main_window._active_tab,
            "set_password",
            lambda pw: called_with.append(pw),
        )
        main_window._on_security_password()
        assert called_with == ["hunter2"]
        # Dialog was constructed with is_encrypted=False
        assert stub.constructed_with[0] is False

    def test_cancel_does_not_call_service(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Negative: Rejected dialog -> no service call."""
        from PySide6.QtWidgets import QDialog

        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(sample_pdf_path)
        stub = _CryptDialogStub(
            exec_result=QDialog.DialogCode.Rejected,
        )
        monkeypatch.setattr(mw_mod, "CryptDialog", stub.make_class())

        called: list = []
        monkeypatch.setattr(
            main_window._active_tab,
            "set_password",
            lambda pw: called.append(pw),
        )
        main_window._on_security_password()
        assert called == []


class TestSecurityPasswordSlotChangePassword:
    """Slot flow: encrypted doc + Change Password."""

    def test_accepted_dialog_calls_change_password(
        self,
        main_window: MainWindow,
        encrypted_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: encrypted tab + Accepted (no remove) -> tab.change_password."""
        from PySide6.QtWidgets import QDialog

        from pdfprism.ui import main_window as mw_mod
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        pw_script = _PasswordDialogStub([(QDialog.DialogCode.Accepted, ENCRYPTED_PDF_PASSWORD)])
        monkeypatch.setattr(mw_mod, "PasswordDialog", pw_script.make_class())
        main_window._open_path(encrypted_pdf_path)

        stub = _CryptDialogStub(
            exec_result=QDialog.DialogCode.Accepted,
            new_password="new_pw",
            remove_requested=False,
        )
        monkeypatch.setattr(mw_mod, "CryptDialog", stub.make_class())

        called_with: list = []
        monkeypatch.setattr(
            main_window._active_tab,
            "change_password",
            lambda pw: called_with.append(pw),
        )
        main_window._on_security_password()
        assert called_with == ["new_pw"]
        # Dialog was constructed with is_encrypted=True
        assert stub.constructed_with[0] is True


class TestSecurityPasswordSlotRemovePassword:
    """Slot flow: encrypted doc + Remove Password (with confirmation)."""

    def test_remove_yes_confirmation_calls_remove_password(
        self,
        main_window: MainWindow,
        encrypted_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: Remove branch + Yes confirmation -> tab.remove_password."""
        from PySide6.QtWidgets import QDialog, QMessageBox

        from pdfprism.ui import main_window as mw_mod
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        pw_script = _PasswordDialogStub([(QDialog.DialogCode.Accepted, ENCRYPTED_PDF_PASSWORD)])
        monkeypatch.setattr(mw_mod, "PasswordDialog", pw_script.make_class())
        main_window._open_path(encrypted_pdf_path)

        stub = _CryptDialogStub(
            exec_result=QDialog.DialogCode.Accepted,
            remove_requested=True,
        )
        monkeypatch.setattr(mw_mod, "CryptDialog", stub.make_class())

        # Auto-answer confirmation Yes
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *a, **k: QMessageBox.StandardButton.Yes,
        )

        called: list = []
        monkeypatch.setattr(
            main_window._active_tab,
            "remove_password",
            lambda: called.append(True),
        )
        main_window._on_security_password()
        assert called == [True]

    def test_remove_no_confirmation_skips_call(
        self,
        main_window: MainWindow,
        encrypted_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Negative: Remove + No confirmation -> no service call."""
        from PySide6.QtWidgets import QDialog, QMessageBox

        from pdfprism.ui import main_window as mw_mod
        from tests.conftest import ENCRYPTED_PDF_PASSWORD

        pw_script = _PasswordDialogStub([(QDialog.DialogCode.Accepted, ENCRYPTED_PDF_PASSWORD)])
        monkeypatch.setattr(mw_mod, "PasswordDialog", pw_script.make_class())
        main_window._open_path(encrypted_pdf_path)

        stub = _CryptDialogStub(
            exec_result=QDialog.DialogCode.Accepted,
            remove_requested=True,
        )
        monkeypatch.setattr(mw_mod, "CryptDialog", stub.make_class())
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *a, **k: QMessageBox.StandardButton.No,
        )

        called: list = []
        monkeypatch.setattr(
            main_window._active_tab,
            "remove_password",
            lambda: called.append(True),
        )
        main_window._on_security_password()
        assert called == []


class TestSecurityPasswordSlotErrorHandling:
    """Errors from the service layer are surfaced via critical dialog."""

    def test_encryption_operation_error_shows_critical(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Negative: EncryptionOperationError -> critical dialog, no crash."""
        from PySide6.QtWidgets import QDialog, QMessageBox

        from pdfprism.core.exceptions import EncryptionOperationError
        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(sample_pdf_path)
        stub = _CryptDialogStub(
            exec_result=QDialog.DialogCode.Accepted,
            new_password="hunter2",
        )
        monkeypatch.setattr(mw_mod, "CryptDialog", stub.make_class())

        def raiser(pw):
            raise EncryptionOperationError("test error")

        monkeypatch.setattr(main_window._active_tab, "set_password", raiser)

        critical_shown: list = []
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            lambda *a, **k: critical_shown.append(a[2] if len(a) > 2 else k.get("text")),
        )
        # Must not raise
        main_window._on_security_password()
        assert len(critical_shown) == 1

    def test_document_save_error_shows_critical(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Negative: DocumentSaveError -> critical dialog, no crash."""
        from PySide6.QtWidgets import QDialog, QMessageBox

        from pdfprism.core.exceptions import DocumentSaveError
        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(sample_pdf_path)
        stub = _CryptDialogStub(
            exec_result=QDialog.DialogCode.Accepted,
            new_password="hunter2",
        )
        monkeypatch.setattr(mw_mod, "CryptDialog", stub.make_class())

        def raiser(pw):
            raise DocumentSaveError("disk full")

        monkeypatch.setattr(main_window._active_tab, "set_password", raiser)

        critical_shown: list = []
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            lambda *a, **k: critical_shown.append(True),
        )
        main_window._on_security_password()
        assert critical_shown == [True]


class TestSecurityPasswordSlotNoActiveTab:
    """Guard: slot is a no-op when no tab is open."""

    def test_no_active_tab_is_noop(self, main_window: MainWindow, monkeypatch) -> None:
        """Negative: no tab -> no CryptDialog constructed."""
        from pdfprism.ui import main_window as mw_mod

        constructed: list = []

        class _ExplodeCrypt:
            def __init__(self, *a, **k):
                constructed.append(True)

        monkeypatch.setattr(mw_mod, "CryptDialog", _ExplodeCrypt)

        assert main_window._active_tab is None
        main_window._on_security_password()  # must not raise
        assert constructed == []


# ---- PR 10.5 regression: password ops must rebind panels + clear cache ---


class TestSecurityPasswordPanelRebind:
    """Regression guard for the AES-decryption-error bug caught in smoke test.

    After in-place save with encryption change, the adapter's underlying
    pymupdf.Document is closed and reopened. Any Page handles held by the
    panels are stale references into the previous Document; MuPDF then
    decrypts content streams with the OLD crypt keys, producing
    'aes padding out of range' + 'syntax error in content stream' spam.

    These tests verify that DocumentView.set_password / change_password /
    remove_password call ``set_adapter`` on every panel (rebind) and clear
    the page cache. Without this the visible output is corrupted.
    """

    def _install_rebind_spy(self, monkeypatch, tab, cache_cleared: list, rebinds: dict) -> None:
        monkeypatch.setattr(
            tab._page_cache,
            "clear",
            lambda: cache_cleared.append(True),
        )
        monkeypatch.setattr(
            tab._thumbnail_panel,
            "set_adapter",
            lambda a: rebinds.setdefault("thumbnail", []).append(a),
        )
        monkeypatch.setattr(
            tab._organize_panel,
            "set_adapter",
            lambda a: rebinds.setdefault("organize", []).append(a),
        )
        monkeypatch.setattr(
            tab._page_view,
            "set_adapter",
            lambda a: rebinds.setdefault("page_view", []).append(a),
        )

    def test_set_password_triggers_rebind(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: set_password clears cache and rebinds all three panels."""
        main_window._open_path(sample_pdf_path)
        tab = main_window._active_tab

        cache_cleared: list = []
        rebinds: dict = {}
        self._install_rebind_spy(monkeypatch, tab, cache_cleared, rebinds)

        # Also stub the service to avoid actual file I/O.
        from pdfprism.services import security as svc_mod

        class _NoopService:
            def __init__(self, adapter):
                self._adapter = adapter

            def set_password(self, pw):
                pass

        monkeypatch.setattr(svc_mod, "SecurityService", _NoopService)

        tab.set_password("test")
        # PR 10.5 detach->save->rebind: each panel's set_adapter is
        # called TWICE. First with None (detach before save so no
        # widget holds a page handle during the in-place doc swap),
        # then with the fresh adapter (rebind after save).
        assert cache_cleared == [True]
        for panel in ("thumbnail", "organize", "page_view"):
            assert panel in rebinds, f"{panel} not rebound"
            assert len(rebinds[panel]) == 2, (
                f"{panel} expected 2 set_adapter calls (detach + rebind), got {len(rebinds[panel])}"
            )
            assert rebinds[panel][0] is None, f"{panel} first call must be None (detach)"
            assert rebinds[panel][1] is tab._adapter, (
                f"{panel} second call must be the current adapter (rebind)"
            )

    def test_change_password_triggers_rebind(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: change_password clears cache + rebinds panels."""
        main_window._open_path(sample_pdf_path)
        tab = main_window._active_tab

        cache_cleared: list = []
        rebinds: dict = {}
        self._install_rebind_spy(monkeypatch, tab, cache_cleared, rebinds)

        from pdfprism.services import security as svc_mod

        class _NoopService:
            def __init__(self, adapter):
                self._adapter = adapter

            def change_password(self, pw):
                pass

        monkeypatch.setattr(svc_mod, "SecurityService", _NoopService)

        tab.change_password("newpw")
        assert cache_cleared == [True]
        for panel in ("thumbnail", "organize", "page_view"):
            assert len(rebinds.get(panel, [])) == 2
            assert rebinds[panel][0] is None
            assert rebinds[panel][1] is tab._adapter

    def test_remove_password_triggers_rebind(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: remove_password clears cache + rebinds panels."""
        main_window._open_path(sample_pdf_path)
        tab = main_window._active_tab

        cache_cleared: list = []
        rebinds: dict = {}
        self._install_rebind_spy(monkeypatch, tab, cache_cleared, rebinds)

        from pdfprism.services import security as svc_mod

        class _NoopService:
            def __init__(self, adapter):
                self._adapter = adapter

            def remove_password(self):
                pass

        monkeypatch.setattr(svc_mod, "SecurityService", _NoopService)

        tab.remove_password()
        assert cache_cleared == [True]
        for panel in ("thumbnail", "organize", "page_view"):
            assert len(rebinds.get(panel, [])) == 2
            assert rebinds[panel][0] is None
            assert rebinds[panel][1] is tab._adapter


# ---- PR 11: File > Properties... integration ----------------------------


class TestPropertiesAction:
    """The Properties action is defined, enable-state-tracked, and menu-placed."""

    def test_action_exists(self, main_window: MainWindow) -> None:
        assert hasattr(main_window, "act_properties")

    def test_action_disabled_empty_state(self, main_window: MainWindow) -> None:
        """Positive: no tabs open -> action disabled."""
        assert main_window._tab_widget.count() == 0
        assert main_window.act_properties.isEnabled() is False

    def test_action_enabled_with_tab(self, main_window: MainWindow, sample_pdf_path: Path) -> None:
        """Positive: opening a document enables the action."""
        main_window._open_path(sample_pdf_path)
        assert main_window.act_properties.isEnabled() is True

    def test_action_present_in_file_menu(self, main_window: MainWindow) -> None:
        """Positive: File menu has a Properties entry pointing at act_properties."""
        # Walk File menu actions and confirm act_properties is among them.
        menubar = main_window.menuBar()
        file_menu = None
        for act in menubar.actions():
            if act.text().replace("&", "") == "File":
                file_menu = act.menu()
                break
        assert file_menu is not None
        actions = file_menu.actions()
        assert main_window.act_properties in actions


class TestPropertiesSlotOK:
    """Slot behavior when the dialog is accepted."""

    def test_accepted_dialog_calls_set_metadata(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: OK -> PropertiesService.set_metadata called with dialog updates."""
        main_window._open_path(sample_pdf_path)

        # Stub PropertiesDialog to auto-accept + expose fake updates
        from pdfprism.ui import main_window as mw_mod

        class _StubDialog:
            def __init__(self, current, parent):
                self._current = current

            def exec(self):
                from PySide6.QtWidgets import QDialog

                return QDialog.DialogCode.Accepted

            def get_updates(self):
                return {"title": "New Title", "author": "New Author"}

            @property
            def delete_xmp_requested(self):
                return False

        monkeypatch.setattr(mw_mod, "PropertiesDialog", _StubDialog)

        # Spy on PropertiesService
        set_metadata_calls: list = []

        class _SpyService:
            def __init__(self, adapter):
                self._adapter = adapter

            def set_metadata(self, updates):
                set_metadata_calls.append(updates)

            def sanitize_metadata(self, delete_xmp=True):
                pass

        monkeypatch.setattr(mw_mod, "PropertiesService", _SpyService)

        # Also stub adapter.save so we don't touch disk during test
        tab = main_window._active_tab
        monkeypatch.setattr(tab._adapter, "save", lambda *a, **kw: None)

        main_window._on_file_properties()

        assert len(set_metadata_calls) == 1
        assert set_metadata_calls[0]["title"] == "New Title"
        assert set_metadata_calls[0]["author"] == "New Author"

    def test_cancel_does_not_call_service(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: Cancel -> no service call."""
        main_window._open_path(sample_pdf_path)

        from pdfprism.ui import main_window as mw_mod

        class _CancelDialog:
            def __init__(self, current, parent):
                pass

            def exec(self):
                from PySide6.QtWidgets import QDialog

                return QDialog.DialogCode.Rejected

            def get_updates(self):
                return {}

            @property
            def delete_xmp_requested(self):
                return False

        monkeypatch.setattr(mw_mod, "PropertiesDialog", _CancelDialog)

        set_metadata_calls: list = []

        class _SpyService:
            def __init__(self, adapter):
                pass

            def set_metadata(self, updates):
                set_metadata_calls.append(updates)

        monkeypatch.setattr(mw_mod, "PropertiesService", _SpyService)

        main_window._on_file_properties()

        assert set_metadata_calls == []


class TestPropertiesSlotXmp:
    """XMP deletion flag routing."""

    def _install_stub_dialog(self, monkeypatch, delete_xmp: bool) -> None:
        from pdfprism.ui import main_window as mw_mod

        class _StubDialog:
            def __init__(self, current, parent):
                pass

            def exec(self):
                from PySide6.QtWidgets import QDialog

                return QDialog.DialogCode.Accepted

            def get_updates(self):
                return {"title": "T"}

            @property
            def delete_xmp_requested(self):
                return delete_xmp

        monkeypatch.setattr(mw_mod, "PropertiesDialog", _StubDialog)

    def test_delete_xmp_true_calls_adapter_method(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: XMP checkbox checked -> adapter.delete_xml_metadata called."""
        main_window._open_path(sample_pdf_path)
        self._install_stub_dialog(monkeypatch, delete_xmp=True)

        tab = main_window._active_tab
        xmp_calls: list = []
        monkeypatch.setattr(tab._adapter, "delete_xml_metadata", lambda: xmp_calls.append(True))
        monkeypatch.setattr(tab._adapter, "save", lambda *a, **kw: None)

        main_window._on_file_properties()
        assert xmp_calls == [True]

    def test_delete_xmp_false_skips_call(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: XMP checkbox unchecked -> adapter.delete_xml_metadata NOT called."""
        main_window._open_path(sample_pdf_path)
        self._install_stub_dialog(monkeypatch, delete_xmp=False)

        tab = main_window._active_tab
        xmp_calls: list = []
        monkeypatch.setattr(tab._adapter, "delete_xml_metadata", lambda: xmp_calls.append(True))
        monkeypatch.setattr(tab._adapter, "save", lambda *a, **kw: None)

        main_window._on_file_properties()
        assert xmp_calls == []


class TestPropertiesSlotErrorHandling:
    """Error paths -- critical dialogs on failure."""

    def test_get_metadata_error_shows_critical(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: adapter.get_metadata raises -> critical dialog."""
        from pdfprism.core.exceptions import PdfPrismError

        main_window._open_path(sample_pdf_path)
        tab = main_window._active_tab

        def _raise():
            raise PdfPrismError("simulated failure")

        monkeypatch.setattr(tab._adapter, "get_metadata", _raise)

        # Capture QMessageBox.critical calls
        from PySide6.QtWidgets import QMessageBox

        crit_calls: list = []
        monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: crit_calls.append(a))

        main_window._on_file_properties()
        assert len(crit_calls) == 1

    def test_save_error_shows_critical(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: save() raises -> critical dialog after OK."""
        from pdfprism.core.exceptions import DocumentSaveError

        main_window._open_path(sample_pdf_path)
        tab = main_window._active_tab

        from pdfprism.ui import main_window as mw_mod

        class _StubDialog:
            def __init__(self, current, parent):
                pass

            def exec(self):
                from PySide6.QtWidgets import QDialog

                return QDialog.DialogCode.Accepted

            def get_updates(self):
                return {"title": "T"}

            @property
            def delete_xmp_requested(self):
                return False

        monkeypatch.setattr(mw_mod, "PropertiesDialog", _StubDialog)

        class _NoopService:
            def __init__(self, adapter):
                pass

            def set_metadata(self, updates):
                pass

        monkeypatch.setattr(mw_mod, "PropertiesService", _NoopService)

        def _raise_save(*a, **kw):
            raise DocumentSaveError("simulated save failure")

        monkeypatch.setattr(tab._adapter, "save", _raise_save)

        from PySide6.QtWidgets import QMessageBox

        crit_calls: list = []
        monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: crit_calls.append(a))

        main_window._on_file_properties()
        assert len(crit_calls) == 1


class TestPropertiesSlotNoActiveTab:
    """Guard: no active tab -> noop."""

    def test_no_active_tab_is_noop(
        self,
        main_window: MainWindow,
        monkeypatch,
    ) -> None:
        """Positive: no active tab -> slot returns without dialog."""
        # No open document
        assert main_window._active_tab is None

        # If the slot tried to open a dialog we would notice via monkeypatched PropertiesDialog
        from pdfprism.ui import main_window as mw_mod

        opened: list = []

        class _WatchedDialog:
            def __init__(self, current, parent):
                opened.append(True)

        monkeypatch.setattr(mw_mod, "PropertiesDialog", _WatchedDialog)

        main_window._on_file_properties()
        assert opened == []


# ---- PR 12: Redaction menu integration ---------------------------------


class TestRedactionMenuAction:
    """Redaction menu actions exist, are enable-state-tracked, and menu-placed."""

    def test_apply_action_exists(self, main_window: MainWindow) -> None:
        assert hasattr(main_window, "act_redaction_apply")

    def test_clear_action_exists(self, main_window: MainWindow) -> None:
        assert hasattr(main_window, "act_redaction_clear")

    def test_disabled_empty_state(self, main_window: MainWindow) -> None:
        """Positive: no tabs open -> both actions disabled."""
        assert main_window._tab_widget.count() == 0
        assert main_window.act_redaction_apply.isEnabled() is False
        assert main_window.act_redaction_clear.isEnabled() is False

    def test_enabled_with_tab(self, main_window: MainWindow, sample_pdf_path: Path) -> None:
        """Positive: opening a document enables both actions."""
        main_window._open_path(sample_pdf_path)
        assert main_window.act_redaction_apply.isEnabled() is True
        assert main_window.act_redaction_clear.isEnabled() is True

    def test_redaction_menu_in_menubar(self, main_window: MainWindow) -> None:
        """Positive: Redaction menu is present in the menu bar."""
        menubar = main_window.menuBar()
        titles = [act.text().replace("&", "") for act in menubar.actions()]
        assert "Redaction" in titles


class TestRedactionApplySlot:
    """_on_redaction_apply slot behaviour."""

    def test_yes_confirmation_applies_and_saves(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: Yes -> service.apply + save called."""
        from pdfprism.core.types import Redaction
        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(sample_pdf_path)
        tab = main_window._active_tab
        adapter = tab._adapter

        # Make list_redactions return non-empty via monkeypatch
        pending = [Redaction(page_index=0, rect=(10.0, 10.0, 100.0, 30.0))]
        apply_calls: list = []
        save_calls: list = []

        class _SpyService:
            def __init__(self, a, **kwargs):
                pass

            def list_redactions(self):
                return pending

            def apply(self, **kwargs):
                apply_calls.append(True)
                return 1

        monkeypatch.setattr(mw_mod, "RedactionService", _SpyService)
        monkeypatch.setattr(adapter, "save", lambda *a, **kw: save_calls.append(True))

        # PR 12.4: dialog rewritten. Call the "apply to original" helper
        # directly to bypass the three-button confirmation dialog.
        service = mw_mod.RedactionService(adapter)
        main_window._apply_redactions_to_original(tab, service)
        assert apply_calls == [True]
        assert save_calls == [True]

    def test_no_confirmation_skips_apply(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: No -> no apply call."""
        from pdfprism.core.types import Redaction
        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(sample_pdf_path)
        pending = [Redaction(page_index=0, rect=(10.0, 10.0, 100.0, 30.0))]
        apply_calls: list = []

        class _SpyService:
            def __init__(self, a, **kwargs):
                pass

            def list_redactions(self):
                return pending

            def apply(self, **kwargs):
                apply_calls.append(True)
                return 1

        monkeypatch.setattr(mw_mod, "RedactionService", _SpyService)

        # PR 12.4: dialog rewritten. Intercept QMessageBox.exec so no
        # button is selected -> clickedButton returns None -> our code
        # falls through without calling either helper (equivalent to Cancel).
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)

        main_window._on_redaction_apply()
        assert apply_calls == []

    def test_empty_pending_shows_info_dialog(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: nothing pending -> info dialog, no service call."""
        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(sample_pdf_path)
        apply_calls: list = []

        class _EmptyService:
            def __init__(self, a, **kwargs):
                pass

            def list_redactions(self):
                return []

            def apply(self, **kwargs):
                apply_calls.append(True)
                return 0

        monkeypatch.setattr(mw_mod, "RedactionService", _EmptyService)

        from PySide6.QtWidgets import QMessageBox

        info_calls: list = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: info_calls.append(True))

        main_window._on_redaction_apply()
        assert info_calls == [True]
        assert apply_calls == []

    def test_apply_error_shows_critical(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: service.apply raises -> critical dialog."""
        from pdfprism.core.exceptions import PdfPrismError
        from pdfprism.core.types import Redaction
        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(sample_pdf_path)
        pending = [Redaction(page_index=0, rect=(10.0, 10.0, 100.0, 30.0))]

        class _RaisingService:
            def __init__(self, a, **kwargs):
                pass

            def list_redactions(self):
                return pending

            def apply(self, **kwargs):
                raise PdfPrismError("boom")

        monkeypatch.setattr(mw_mod, "RedactionService", _RaisingService)

        # PR 12.4: intercept QMessageBox.critical from helper directly.
        from PySide6.QtWidgets import QMessageBox

        crit_calls: list = []
        monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: crit_calls.append(True))

        # Call the "apply to original" helper directly, bypassing the dialog.
        tab = main_window._active_tab
        service = _RaisingService(tab._adapter)
        main_window._apply_redactions_to_original(tab, service)
        assert crit_calls == [True]

    def test_no_active_tab_is_noop(self, main_window: MainWindow, monkeypatch) -> None:
        """Positive: no active tab -> no-op."""
        assert main_window._active_tab is None
        from pdfprism.ui import main_window as mw_mod

        constructed: list = []

        class _CountingService:
            def __init__(self, a):
                constructed.append(True)

        monkeypatch.setattr(mw_mod, "RedactionService", _CountingService)

        main_window._on_redaction_apply()
        assert constructed == []


class TestRedactionClearSlot:
    """_on_redaction_clear slot behaviour."""

    def test_clears_all_pending(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: all pending marks removed via adapter.remove_redaction."""
        from pdfprism.core.types import Redaction
        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(sample_pdf_path)
        tab = main_window._active_tab
        adapter = tab._adapter

        # Two pending on page 0, one on page 1 (if fixture has page 1)
        pending = [
            Redaction(page_index=0, rect=(10.0, 10.0, 100.0, 30.0)),
            Redaction(page_index=0, rect=(120.0, 10.0, 200.0, 30.0)),
        ]

        class _SpyService:
            def __init__(self, a, **kwargs):
                pass

            def list_redactions(self):
                return pending

        monkeypatch.setattr(mw_mod, "RedactionService", _SpyService)

        remove_calls: list = []
        monkeypatch.setattr(adapter, "remove_redaction", lambda p, i: remove_calls.append((p, i)))

        main_window._on_redaction_clear()
        # Two calls to remove_redaction (order: reverse per page)
        assert len(remove_calls) == 2
        # Both on page 0
        assert all(p == 0 for p, i in remove_calls)

    def test_empty_pending_status_message(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: nothing pending -> status message, no adapter call."""
        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(sample_pdf_path)
        tab = main_window._active_tab
        adapter = tab._adapter

        class _EmptyService:
            def __init__(self, a, **kwargs):
                pass

            def list_redactions(self):
                return []

        monkeypatch.setattr(mw_mod, "RedactionService", _EmptyService)
        remove_calls: list = []
        monkeypatch.setattr(adapter, "remove_redaction", lambda p, i: remove_calls.append((p, i)))

        main_window._on_redaction_clear()
        assert remove_calls == []

    def test_no_active_tab_is_noop(self, main_window: MainWindow, monkeypatch) -> None:
        """Positive: no active tab -> no-op."""
        assert main_window._active_tab is None
        from pdfprism.ui import main_window as mw_mod

        constructed: list = []

        class _CountingService:
            def __init__(self, a):
                constructed.append(True)

        monkeypatch.setattr(mw_mod, "RedactionService", _CountingService)

        main_window._on_redaction_clear()
        assert constructed == []


# ---- Menu order convention ----------------------------------------------


class TestMenuOrder:
    """Standard menu order: Help is always last."""

    def test_help_is_last(self, main_window: MainWindow) -> None:
        """Positive: Help sits at the end of the menu bar (universal convention)."""
        menubar = main_window.menuBar()
        titles = [a.text().replace("&", "") for a in menubar.actions()]
        assert titles[-1] == "Help", f"Menu order was {titles}; Help must be last"

    def test_expected_order(self, main_window: MainWindow) -> None:
        """Positive: full menu order is stable."""
        menubar = main_window.menuBar()
        titles = [a.text().replace("&", "") for a in menubar.actions()]
        expected = ["File", "Edit", "View", "Redaction", "Go", "Help"]
        assert titles == expected


# ---- PR 12.2: Search-and-redact --------------------------------------


class TestSearchAndRedactMenuAction:
    def test_action_exists(self, main_window: MainWindow) -> None:
        assert hasattr(main_window, "act_redaction_search")

    def test_enabled_with_tab(self, main_window: MainWindow, sample_pdf_path: Path) -> None:
        main_window._open_path(sample_pdf_path)
        assert main_window.act_redaction_search.isEnabled() is True


class TestSearchAndRedactSlot:
    def test_ok_with_hits_calls_service(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: OK -> RedactionService.redact_hits called."""
        from pdfprism.core.types import SearchHit
        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(sample_pdf_path)

        stub_hits = [
            SearchHit(page_index=0, x0=0.0, y0=0.0, x1=10.0, y1=10.0),
        ]

        class _StubDialog:
            def __init__(self, adapter, parent):
                pass

            def exec(self):
                from PySide6.QtWidgets import QDialog

                return QDialog.DialogCode.Accepted

            def selected_hits(self):
                return stub_hits

        monkeypatch.setattr(mw_mod, "SearchRedactDialog", _StubDialog)

        calls: list = []

        class _SpyService:
            def __init__(self, a, **kwargs):
                pass

            def redact_hits(self, hits):
                calls.append(hits)
                return len(hits)

        monkeypatch.setattr(mw_mod, "RedactionService", _SpyService)

        main_window._on_redaction_search()
        assert len(calls) == 1
        assert calls[0] == stub_hits

    def test_cancel_no_service_call(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: Cancel -> no service call."""
        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(sample_pdf_path)

        class _CancelDialog:
            def __init__(self, adapter, parent):
                pass

            def exec(self):
                from PySide6.QtWidgets import QDialog

                return QDialog.DialogCode.Rejected

            def selected_hits(self):
                return []

        monkeypatch.setattr(mw_mod, "SearchRedactDialog", _CancelDialog)

        calls: list = []

        class _SpyService:
            def __init__(self, a, **kwargs):
                pass

            def redact_hits(self, hits):
                calls.append(hits)
                return len(hits)

        monkeypatch.setattr(mw_mod, "RedactionService", _SpyService)

        main_window._on_redaction_search()
        assert calls == []


# ---- PR 12.3: Redaction Options -----------------------------------------


class TestRedactionOptionsAction:
    def test_action_exists(self, main_window: MainWindow) -> None:
        assert hasattr(main_window, "act_redaction_options")

    def test_action_always_enabled(self, main_window: MainWindow) -> None:
        """Positive: options are session-config; enabled without a tab."""
        assert main_window.act_redaction_options.isEnabled() is True

    def test_initial_defaults(self, main_window: MainWindow) -> None:
        """Positive: fresh MainWindow has sensible defaults for session values."""
        assert main_window._redaction_fill_color == (0, 0, 0)
        assert main_window._redaction_replacement_text is None
        assert main_window._redaction_images == 2
        assert main_window._redaction_graphics == 1
        assert main_window._redaction_text == 0


class TestRedactionOptionsSlot:
    def test_ok_updates_in_memory_state(self, main_window: MainWindow, monkeypatch) -> None:
        """Positive: OK dialog updates MainWindow session attrs."""
        from pdfprism.ui import main_window as mw_mod

        class _StubDialog:
            def __init__(self, **kwargs):
                pass

            def exec(self):
                from PySide6.QtWidgets import QDialog

                return QDialog.DialogCode.Accepted

            @property
            def fill_color(self):
                return (200, 100, 50)

            @property
            def replacement_text(self):
                return "[X]"

            @property
            def images(self):
                return 1

            @property
            def graphics(self):
                return 0

            @property
            def text_mode(self):
                return 1

        monkeypatch.setattr(mw_mod, "RedactionOptionsDialog", _StubDialog)

        main_window._on_redaction_options()
        assert main_window._redaction_fill_color == (200, 100, 50)
        assert main_window._redaction_replacement_text == "[X]"
        assert main_window._redaction_images == 1
        assert main_window._redaction_graphics == 0
        assert main_window._redaction_text == 1

    def test_cancel_does_not_change_state(self, main_window: MainWindow, monkeypatch) -> None:
        """Positive: Cancel leaves session attrs unchanged."""
        from pdfprism.ui import main_window as mw_mod

        original_color = main_window._redaction_fill_color

        class _CancelDialog:
            def __init__(self, **kwargs):
                pass

            def exec(self):
                from PySide6.QtWidgets import QDialog

                return QDialog.DialogCode.Rejected

        monkeypatch.setattr(mw_mod, "RedactionOptionsDialog", _CancelDialog)

        main_window._on_redaction_options()
        assert main_window._redaction_fill_color == original_color


# ---- PR 12.4: Apply Save-As flow -----------------------------------


class TestApplySaveAsCancel:
    """Confirmation dialog: Cancel button dismisses without action."""

    def test_cancel_dismisses(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: no click on any button -> neither helper invoked."""
        from PySide6.QtWidgets import QMessageBox

        from pdfprism.core.types import Redaction
        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(sample_pdf_path)
        pending = [Redaction(page_index=0, rect=(10.0, 10.0, 100.0, 30.0))]

        class _StubService:
            def __init__(self, a, **kwargs):
                pass

            def list_redactions(self):
                return pending

        monkeypatch.setattr(mw_mod, "RedactionService", _StubService)

        # QMessageBox.exec returns without clicking anything -> clickedButton = None
        monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)

        # Spy on both helpers -- neither should be called
        to_original_calls: list = []
        save_as_calls: list = []
        monkeypatch.setattr(
            main_window,
            "_apply_redactions_to_original",
            lambda *a, **kw: to_original_calls.append(True),
        )
        monkeypatch.setattr(
            main_window,
            "_apply_redactions_and_save_as",
            lambda *a, **kw: save_as_calls.append(True),
        )

        main_window._on_redaction_apply()
        assert to_original_calls == []
        assert save_as_calls == []


class TestApplyAndSaveAsHelper:
    """_apply_redactions_and_save_as flow."""

    def test_happy_path(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        mutable_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: save copy, open new tab, apply, save."""
        from PySide6.QtWidgets import QFileDialog

        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(mutable_pdf_path)
        original_tab = main_window._active_tab
        original_adapter = original_tab._adapter

        new_path = tmp_path / "smoke_saveas_copy.pdf"

        # Auto-select the new path in QFileDialog
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *a, **kw: (str(new_path), "PDF files (*.pdf)"),
        )

        # Spy on adapter.save at source (which does the copy)
        original_save_calls: list = []
        real_save = original_adapter.save

        def spy_save(path=None, **kw):
            original_save_calls.append(path)
            return real_save(path=path, **kw)

        monkeypatch.setattr(original_adapter, "save", spy_save)

        # Fake service (works on any adapter)
        apply_calls: list = []

        class _StubService:
            def __init__(self, a, **kwargs):
                self.adapter = a

            def list_redactions(self):
                return []

            def apply(self, **kwargs):
                apply_calls.append(True)
                return 1

        monkeypatch.setattr(mw_mod, "RedactionService", _StubService)

        service = _StubService(original_adapter)
        main_window._apply_redactions_and_save_as(original_tab, original_adapter, service)

        # source adapter should have been asked to save to new_path
        assert new_path in original_save_calls
        # apply was called (on the new tab's adapter)
        assert apply_calls == [True]
        # A new tab should be open
        assert main_window._tab_widget.count() >= 2

    def test_user_cancels_file_dialog(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: user cancels QFileDialog -> full abort, no side effects."""
        from PySide6.QtWidgets import QFileDialog

        main_window._open_path(mutable_pdf_path)
        tab = main_window._active_tab
        adapter = tab._adapter

        # QFileDialog cancel returns empty string
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *a, **kw: ("", ""),
        )

        # Spy on adapter.save -- should NOT be called on cancel
        save_calls: list = []
        monkeypatch.setattr(adapter, "save", lambda *a, **kw: save_calls.append(True))

        class _StubService:
            def __init__(self, a, **kwargs):
                pass

        service = _StubService(adapter)
        main_window._apply_redactions_and_save_as(tab, adapter, service)

        assert save_calls == []
        # Still only one tab
        assert main_window._tab_widget.count() == 1

    def test_source_save_error_shows_critical(
        self,
        main_window: MainWindow,
        mutable_pdf_path: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: adapter.save() on source copy fails -> critical dialog."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        from pdfprism.core.exceptions import DocumentSaveError

        main_window._open_path(mutable_pdf_path)
        tab = main_window._active_tab
        adapter = tab._adapter

        new_path = tmp_path / "will_fail.pdf"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *a, **kw: (str(new_path), ""),
        )
        monkeypatch.setattr(
            adapter,
            "save",
            lambda *a, **kw: (_ for _ in ()).throw(DocumentSaveError("boom")),
        )

        crit_calls: list = []
        monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: crit_calls.append(True))

        class _StubService:
            def __init__(self, a, **kwargs):
                pass

        main_window._apply_redactions_and_save_as(tab, adapter, _StubService(adapter))
        assert crit_calls == [True]

    def test_no_path_shows_critical(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: tab.path is None -> critical dialog, no save attempt."""
        from PySide6.QtWidgets import QMessageBox

        main_window._open_path(sample_pdf_path)
        tab = main_window._active_tab
        adapter = tab._adapter

        # Force tab.path to None -- simulates orphan tab
        monkeypatch.setattr(type(tab), "path", property(lambda s: None))

        crit_calls: list = []
        monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: crit_calls.append(True))

        class _StubService:
            def __init__(self, a, **kwargs):
                pass

        main_window._apply_redactions_and_save_as(tab, adapter, _StubService(adapter))
        assert crit_calls == [True]


# ---- PR 14a: Options change restyles pending marks ---------------


class TestRestylePendingMatchingOldDefaults:
    def test_no_op_when_old_equals_new(self, main_window: MainWindow, monkeypatch) -> None:
        """Positive: helper returns early when old == new."""
        from pdfprism.ui import main_window as mw_mod

        call_log: list = []

        class _SpyService:
            def __init__(self, a, **kwargs):
                pass

            def update_pending_matching_defaults(self, current_defaults, new_defaults):
                call_log.append((current_defaults, new_defaults))
                return 0

        monkeypatch.setattr(mw_mod, "RedactionService", _SpyService)

        main_window._restyle_pending_matching_old_defaults(
            old_fill=main_window._redaction_fill_color,
            old_text=main_window._redaction_replacement_text,
        )
        # No update call: helper returned early
        assert call_log == []

    def test_iterates_open_tabs(
        self,
        main_window: MainWindow,
        sample_pdf_path: Path,
        monkeypatch,
    ) -> None:
        """Positive: helper calls update on each open tab's adapter."""
        from pdfprism.ui import main_window as mw_mod

        main_window._open_path(sample_pdf_path)
        call_log: list = []

        class _SpyService:
            def __init__(self, a, **kwargs):
                pass

            def update_pending_matching_defaults(self, current_defaults, new_defaults):
                call_log.append((current_defaults, new_defaults))
                return 0

        monkeypatch.setattr(mw_mod, "RedactionService", _SpyService)

        # Simulate: change happened
        old_fill = (0, 0, 0)
        old_text: str | None = None
        main_window._redaction_fill_color = (255, 0, 0)
        main_window._redaction_replacement_text = "[NEW]"

        main_window._restyle_pending_matching_old_defaults(old_fill=old_fill, old_text=old_text)
        assert len(call_log) == 1
        current_defaults, new_defaults = call_log[0]
        assert current_defaults == (old_fill, old_text)
        assert new_defaults == ((255, 0, 0), "[NEW]")


# ---- PR 14c: Manage Marks slot -----------------------------------


class TestOnRedactionManage:
    def test_no_op_when_no_tab_open(self, main_window) -> None:
        """Positive: no active tab -> _on_redaction_manage returns silently."""
        # Nothing raises
        main_window._on_redaction_manage()

    def test_opens_dialog_when_tab_open(self, main_window, sample_pdf_path, monkeypatch) -> None:
        """Positive: with tab open, slot instantiates + exec()s dialog."""
        main_window._open_path(sample_pdf_path)

        exec_calls: list = []

        class _StubDialog:
            def __init__(self, **kwargs):
                exec_calls.append(kwargs)

            def exec(self):
                return 1

            @property
            def changed(self):
                # Return an object with a .connect method
                class _Sig:
                    def connect(self, cb):
                        pass

                return _Sig()

        import pdfprism.ui.main_window as mw_mod

        monkeypatch.setattr(mw_mod, "ManageMarksDialog", _StubDialog)

        main_window._on_redaction_manage()
        assert len(exec_calls) == 1

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

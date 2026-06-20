"""Tests for SearchBar."""

import pytest
from PySide6.QtCore import Qt

from pdfprism.services.search import SearchScope
from pdfprism.ui.widgets.search_bar import SearchBar


@pytest.fixture
def bar(qtbot) -> SearchBar:
    b = SearchBar()
    b.resize(600, 40)
    qtbot.addWidget(b)
    return b


class TestInitialState:
    def test_search_term_empty(self, bar: SearchBar) -> None:
        assert bar.search_term == ""


class TestFindSubmission:
    def test_return_emits_find_requested_with_term(self, bar: SearchBar, qtbot) -> None:
        bar._input.setText("hello")
        with qtbot.waitSignal(bar.find_requested, timeout=1000) as blocker:
            bar._input.returnPressed.emit()
        assert blocker.args == ["hello"]

    def test_return_strips_whitespace(self, bar: SearchBar, qtbot) -> None:
        bar._input.setText("  hello  ")
        with qtbot.waitSignal(bar.find_requested, timeout=1000) as blocker:
            bar._input.returnPressed.emit()
        assert blocker.args == ["hello"]

    def test_return_with_empty_input_does_not_emit(self, bar: SearchBar, qtbot) -> None:
        bar._input.setText("")
        with qtbot.assertNotEmitted(bar.find_requested, wait=100):
            bar._input.returnPressed.emit()


class TestButtons:
    def test_next_button_emits(self, bar: SearchBar, qtbot) -> None:
        with qtbot.waitSignal(bar.next_requested, timeout=1000):
            bar._next_btn.click()

    def test_prev_button_emits(self, bar: SearchBar, qtbot) -> None:
        with qtbot.waitSignal(bar.prev_requested, timeout=1000):
            bar._prev_btn.click()

    def test_close_button_emits(self, bar: SearchBar, qtbot) -> None:
        with qtbot.waitSignal(bar.closed, timeout=1000):
            bar._close_btn.click()


class TestEscape:
    def test_escape_in_input_emits_closed(self, bar: SearchBar, qtbot) -> None:
        bar._input.setFocus()
        with qtbot.waitSignal(bar.closed, timeout=1000):
            qtbot.keyClick(bar._input, Qt.Key.Key_Escape)


class TestCounter:
    def test_set_match_count_normal(self, bar: SearchBar) -> None:
        bar.set_match_count(3, 27)
        assert bar._counter_label.text() == "3 of 27"

    def test_set_match_count_zero_shows_no_matches(self, bar: SearchBar) -> None:
        bar.set_match_count(0, 0)
        assert bar._counter_label.text() == "No matches"


class TestClear:
    def test_clear_resets_input_and_counter(self, bar: SearchBar) -> None:
        bar._input.setText("hello")
        bar.set_match_count(3, 27)
        bar.clear()
        assert bar.search_term == ""
        assert bar._counter_label.text() == ""


class TestScope:
    def test_default_scope_is_current(self, bar: SearchBar) -> None:
        assert bar.search_scope == SearchScope.CURRENT

    def test_changing_scope_updates_property(self, bar: SearchBar) -> None:
        bar._scope_combo.setCurrentIndex(1)
        assert bar.search_scope == SearchScope.ALL_OPEN

    def test_clear_does_not_reset_scope(self, bar: SearchBar) -> None:
        bar._scope_combo.setCurrentIndex(1)
        bar.clear()
        assert bar.search_scope == SearchScope.ALL_OPEN


class TestAggregateCount:
    def test_zero_total_shows_no_matches(self, bar: SearchBar) -> None:
        bar.set_aggregate_count(0, 0)
        assert bar._counter_label.text() == "No matches"

    def test_single_doc_shows_matches(self, bar: SearchBar) -> None:
        bar.set_aggregate_count(5, 1)
        assert bar._counter_label.text() == "5 matches"

    def test_multi_doc_shows_total_in_docs(self, bar: SearchBar) -> None:
        bar.set_aggregate_count(9, 2)
        assert bar._counter_label.text() == "9 in 2 docs"


class TestAggregatePosition:
    def test_current_zero_falls_back_to_aggregate(self, bar: SearchBar) -> None:
        bar.set_aggregate_count(5, 1, 0)
        assert bar._counter_label.text() == "5 matches"

    def test_single_doc_with_cursor(self, bar: SearchBar) -> None:
        bar.set_aggregate_count(5, 1, 3)
        assert bar._counter_label.text() == "3 of 5"

    def test_multi_doc_with_cursor(self, bar: SearchBar) -> None:
        bar.set_aggregate_count(9, 2, 4)
        assert bar._counter_label.text() == "4 of 9 in 2 docs"

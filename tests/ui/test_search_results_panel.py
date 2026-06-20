"""Tests for the SearchResultsPanel widget."""

import pytest

from pdfprism.core.types import CrossDocHit, SearchHit
from pdfprism.ui.widgets.search_results_panel import SearchResultsPanel


@pytest.fixture
def panel(qtbot) -> SearchResultsPanel:
    p = SearchResultsPanel()
    qtbot.addWidget(p)
    return p


def _hit(page: int, x: float = 0.0) -> SearchHit:
    return SearchHit(page_index=page, x0=x, y0=0.0, x1=x + 100.0, y1=20.0)


class TestEmpty:
    def test_no_items_initially(self, panel: SearchResultsPanel) -> None:
        assert panel._tree.topLevelItemCount() == 0


class TestSetResults:
    def test_empty_results_leaves_tree_empty(self, panel: SearchResultsPanel) -> None:
        panel.set_results([], ["a.pdf", "b.pdf"])
        assert panel._tree.topLevelItemCount() == 0

    def test_results_grouped_by_doc(self, panel: SearchResultsPanel) -> None:
        results = [
            CrossDocHit(doc_index=0, hit=_hit(0)),
            CrossDocHit(doc_index=0, hit=_hit(1)),
            CrossDocHit(doc_index=1, hit=_hit(0)),
        ]
        panel.set_results(results, ["a.pdf", "b.pdf"])
        assert panel._tree.topLevelItemCount() == 2
        assert panel._tree.topLevelItem(0).childCount() == 2
        assert panel._tree.topLevelItem(1).childCount() == 1

    def test_doc_node_shows_filename_and_count(self, panel: SearchResultsPanel) -> None:
        results = [
            CrossDocHit(doc_index=0, hit=_hit(0)),
            CrossDocHit(doc_index=0, hit=_hit(1)),
        ]
        panel.set_results(results, ["report.pdf"])
        assert panel._tree.topLevelItem(0).text(0) == "report.pdf (2 hits)"

    def test_hit_node_shows_one_based_page(self, panel: SearchResultsPanel) -> None:
        results = [CrossDocHit(doc_index=0, hit=_hit(4))]
        panel.set_results(results, ["a.pdf"])
        doc_item = panel._tree.topLevelItem(0)
        assert doc_item.child(0).text(0) == "Page 5"

    def test_set_results_replaces_previous(self, panel: SearchResultsPanel) -> None:
        panel.set_results([CrossDocHit(doc_index=0, hit=_hit(0))], ["a.pdf"])
        panel.set_results([CrossDocHit(doc_index=0, hit=_hit(2))], ["b.pdf"])
        assert panel._tree.topLevelItemCount() == 1
        assert panel._tree.topLevelItem(0).text(0) == "b.pdf (1 hits)"

    def test_missing_title_falls_back_to_generic(self, panel: SearchResultsPanel) -> None:
        results = [CrossDocHit(doc_index=2, hit=_hit(0))]
        panel.set_results(results, ["a.pdf"])
        assert "Document 2" in panel._tree.topLevelItem(0).text(0)


class TestSignals:
    def test_click_on_hit_emits_index(self, panel: SearchResultsPanel, qtbot) -> None:
        results = [
            CrossDocHit(doc_index=0, hit=_hit(0)),
            CrossDocHit(doc_index=0, hit=_hit(1)),
            CrossDocHit(doc_index=1, hit=_hit(0)),
        ]
        panel.set_results(results, ["a.pdf", "b.pdf"])
        doc0 = panel._tree.topLevelItem(0)
        hit_item = doc0.child(1)
        with qtbot.waitSignal(panel.result_selected, timeout=1000) as blocker:
            panel._tree.itemClicked.emit(hit_item, 0)
        assert blocker.args == [1]

    def test_click_on_doc_node_does_not_emit(self, panel: SearchResultsPanel, qtbot) -> None:
        results = [CrossDocHit(doc_index=0, hit=_hit(0))]
        panel.set_results(results, ["a.pdf"])
        doc_item = panel._tree.topLevelItem(0)
        with qtbot.assertNotEmitted(panel.result_selected, wait=100):
            panel._tree.itemClicked.emit(doc_item, 0)


class TestSelection:
    def test_set_current_highlights_matching_hit(self, panel: SearchResultsPanel) -> None:
        results = [
            CrossDocHit(doc_index=0, hit=_hit(0)),
            CrossDocHit(doc_index=1, hit=_hit(2)),
        ]
        panel.set_results(results, ["a.pdf", "b.pdf"])
        panel.set_current(1)
        assert panel._tree.currentItem() is panel._tree.topLevelItem(1).child(0)

    def test_set_current_with_unknown_index_is_noop(self, panel: SearchResultsPanel) -> None:
        results = [CrossDocHit(doc_index=0, hit=_hit(0))]
        panel.set_results(results, ["a.pdf"])
        panel.set_current(99)
        # No crash; selection state unchanged.

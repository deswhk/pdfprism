"""Tests for OutlinePanel and OutlineModel."""

import pytest
from PySide6.QtCore import Qt

from pdfprism.core.types import OutlineItem
from pdfprism.ui.widgets.outline_panel import OutlinePanel


@pytest.fixture
def panel(qtbot) -> OutlinePanel:
    p = OutlinePanel()
    p.resize(200, 600)
    qtbot.addWidget(p)
    return p


@pytest.fixture
def sample_outline() -> list[OutlineItem]:
    return [
        OutlineItem(level=1, title="Chapter 1: Introduction", page_index=0),
        OutlineItem(level=2, title="1.1 Overview", page_index=0),
        OutlineItem(level=2, title="1.2 Background", page_index=1),
        OutlineItem(level=1, title="Chapter 2: Conclusion", page_index=2),
    ]


class TestEmpty:
    def test_no_rows_initially(self, panel: OutlinePanel) -> None:
        assert panel.model().rowCount() == 0


class TestPopulated:
    def test_set_outline_creates_two_root_rows(
        self, panel: OutlinePanel, sample_outline: list[OutlineItem]
    ) -> None:
        panel.set_outline(sample_outline)
        assert panel.model().rowCount() == 2

    def test_chapter_1_has_two_children(
        self, panel: OutlinePanel, sample_outline: list[OutlineItem]
    ) -> None:
        panel.set_outline(sample_outline)
        model = panel.model()
        ch1 = model.index(0, 0)
        assert model.rowCount(ch1) == 2

    def test_chapter_2_has_no_children(
        self, panel: OutlinePanel, sample_outline: list[OutlineItem]
    ) -> None:
        panel.set_outline(sample_outline)
        model = panel.model()
        ch2 = model.index(1, 0)
        assert model.rowCount(ch2) == 0

    def test_root_titles(self, panel: OutlinePanel, sample_outline: list[OutlineItem]) -> None:
        panel.set_outline(sample_outline)
        model = panel.model()
        assert (
            model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "Chapter 1: Introduction"
        )
        assert model.data(model.index(1, 0), Qt.ItemDataRole.DisplayRole) == "Chapter 2: Conclusion"

    def test_subsection_titles(
        self, panel: OutlinePanel, sample_outline: list[OutlineItem]
    ) -> None:
        panel.set_outline(sample_outline)
        model = panel.model()
        ch1 = model.index(0, 0)
        assert model.data(model.index(0, 0, ch1), Qt.ItemDataRole.DisplayRole) == "1.1 Overview"
        assert model.data(model.index(1, 0, ch1), Qt.ItemDataRole.DisplayRole) == "1.2 Background"

    def test_parent_navigation(
        self, panel: OutlinePanel, sample_outline: list[OutlineItem]
    ) -> None:
        panel.set_outline(sample_outline)
        model = panel.model()
        ch1 = model.index(0, 0)
        sub = model.index(1, 0, ch1)
        assert model.parent(sub) == ch1
        assert not model.parent(ch1).isValid()

    def test_set_outline_replaces_previous(
        self, panel: OutlinePanel, sample_outline: list[OutlineItem]
    ) -> None:
        panel.set_outline(sample_outline)
        panel.set_outline([])
        assert panel.model().rowCount() == 0


class TestSignals:
    def test_click_chapter_emits_correct_page(
        self,
        panel: OutlinePanel,
        sample_outline: list[OutlineItem],
        qtbot,
    ) -> None:
        panel.set_outline(sample_outline)
        ch1 = panel.model().index(0, 0)
        with qtbot.waitSignal(panel.page_selected, timeout=1000) as blocker:
            panel.clicked.emit(ch1)
        assert blocker.args == [0]

    def test_click_subsection_emits_correct_page(
        self,
        panel: OutlinePanel,
        sample_outline: list[OutlineItem],
        qtbot,
    ) -> None:
        panel.set_outline(sample_outline)
        model = panel.model()
        sub = model.index(1, 0, model.index(0, 0))  # "1.2 Background" -> page 1
        with qtbot.waitSignal(panel.page_selected, timeout=1000) as blocker:
            panel.clicked.emit(sub)
        assert blocker.args == [1]

    def test_click_second_chapter_emits_correct_page(
        self,
        panel: OutlinePanel,
        sample_outline: list[OutlineItem],
        qtbot,
    ) -> None:
        panel.set_outline(sample_outline)
        ch2 = panel.model().index(1, 0)
        with qtbot.waitSignal(panel.page_selected, timeout=1000) as blocker:
            panel.clicked.emit(ch2)
        assert blocker.args == [2]

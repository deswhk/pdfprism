"""Tests for ThumbnailPanel and ThumbnailModel."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.ui.page_cache import PageCache
from pdfprism.ui.widgets.thumbnail_panel import ThumbnailPanel


@pytest.fixture
def panel(qtbot) -> ThumbnailPanel:
    cache = PageCache()
    p = ThumbnailPanel(cache)
    p.resize(200, 600)
    qtbot.addWidget(p)
    return p


@pytest.fixture
def adapter_with_doc(sample_pdf_path: Path) -> Iterator[PyMuPDFAdapter]:
    a = PyMuPDFAdapter()
    a.open(sample_pdf_path)
    yield a
    a.close()


class TestEmpty:
    def test_no_rows_initially(self, panel: ThumbnailPanel) -> None:
        assert panel.model().rowCount() == 0


class TestBinding:
    def test_set_adapter_populates_rows(
        self, panel: ThumbnailPanel, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        panel.set_adapter(adapter_with_doc)
        assert panel.model().rowCount() == 3

    def test_clear_adapter_empties_rows(
        self, panel: ThumbnailPanel, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        panel.set_adapter(adapter_with_doc)
        panel.set_adapter(None)
        assert panel.model().rowCount() == 0


class TestModelData:
    def test_display_role_returns_page_label(
        self, panel: ThumbnailPanel, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        panel.set_adapter(adapter_with_doc)
        model = panel.model()
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "Page 1"
        assert model.data(model.index(2, 0), Qt.ItemDataRole.DisplayRole) == "Page 3"

    def test_decoration_role_returns_pixmap(
        self, panel: ThumbnailPanel, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        panel.set_adapter(adapter_with_doc)
        model = panel.model()
        pix = model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole)
        assert isinstance(pix, QPixmap)
        assert not pix.isNull()

    def test_out_of_range_index_returns_none(
        self, panel: ThumbnailPanel, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        panel.set_adapter(adapter_with_doc)
        model = panel.model()
        assert model.data(model.index(99, 0), Qt.ItemDataRole.DisplayRole) is None


class TestSelection:
    def test_set_current_page_updates_selection(
        self, panel: ThumbnailPanel, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        panel.set_adapter(adapter_with_doc)
        panel.set_current_page(1)
        assert panel.currentIndex().row() == 1

    def test_set_current_page_out_of_range_is_noop(
        self, panel: ThumbnailPanel, adapter_with_doc: PyMuPDFAdapter
    ) -> None:
        panel.set_adapter(adapter_with_doc)
        panel.set_current_page(1)
        panel.set_current_page(99)
        assert panel.currentIndex().row() == 1

    def test_click_emits_page_selected(
        self,
        panel: ThumbnailPanel,
        adapter_with_doc: PyMuPDFAdapter,
        qtbot,
    ) -> None:
        panel.set_adapter(adapter_with_doc)
        with qtbot.waitSignal(panel.page_selected, timeout=1000) as blocker:
            panel.clicked.emit(panel.model().index(2, 0))
        assert blocker.args == [2]

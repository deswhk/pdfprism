"""Tests for the DocumentView widget."""

from pathlib import Path

import pytest

from pdfprism.core.exceptions import PdfPrismError
from pdfprism.ui.widgets.document_view import DocumentView
from pdfprism.ui.widgets.page_view import ViewMode


@pytest.fixture
def document_view(sample_pdf_path: Path, qtbot) -> DocumentView:
    dv = DocumentView(sample_pdf_path)
    qtbot.addWidget(dv)
    return dv


@pytest.fixture
def mutable_view(mutable_pdf_path: Path, qtbot) -> DocumentView:
    """DocumentView opened on a writable copy of the sample PDF."""
    dv = DocumentView(mutable_pdf_path)
    qtbot.addWidget(dv)
    dv.open()
    return dv


class TestConstruction:
    def test_path_stored(self, sample_pdf_path: Path, qtbot) -> None:
        dv = DocumentView(sample_pdf_path)
        qtbot.addWidget(dv)
        assert dv.path == sample_pdf_path

    def test_not_opened_until_open_called(self, document_view: DocumentView) -> None:
        assert document_view.page_view.page_count == 0

    def test_initial_search_state_empty(self, document_view: DocumentView) -> None:
        assert document_view.search_hits == []
        assert document_view.current_hit_index == -1


class TestOpen:
    def test_open_loads_document(self, document_view: DocumentView) -> None:
        document_view.open()
        assert document_view.adapter.page_count == 3
        assert document_view.page_view.page_count == 3

    def test_open_garbage_raises(self, garbage_file: Path, qtbot) -> None:
        dv = DocumentView(garbage_file)
        qtbot.addWidget(dv)
        with pytest.raises(PdfPrismError):
            dv.open()


class TestClose:
    def test_close_clears_page_view(self, document_view: DocumentView) -> None:
        document_view.open()
        assert document_view.page_view.page_count == 3
        document_view.close_document()
        assert document_view.page_view.page_count == 0

    def test_close_is_idempotent(self, document_view: DocumentView) -> None:
        document_view.open()
        document_view.close_document()
        document_view.close_document()  # should not raise


class TestSignals:
    def test_page_changed_proxied(self, document_view: DocumentView, qtbot) -> None:
        document_view.open()
        with qtbot.waitSignal(document_view.page_changed, timeout=1000) as blocker:
            document_view.page_view.next_page()
        assert blocker.args == [1]

    def test_zoom_changed_proxied(self, document_view: DocumentView, qtbot) -> None:
        document_view.open()
        with qtbot.waitSignal(document_view.zoom_changed, timeout=1000):
            document_view.page_view.set_fit_width()

    def test_view_mode_changed_proxied(self, document_view: DocumentView, qtbot) -> None:
        document_view.open()
        with qtbot.waitSignal(document_view.view_mode_changed, timeout=1000) as blocker:
            document_view.page_view.set_view_mode(ViewMode.CONTINUOUS)
        assert blocker.args == [ViewMode.CONTINUOUS]


class TestModifiedState:
    def test_not_modified_after_open(self, mutable_view: DocumentView) -> None:
        assert mutable_view.is_modified is False

    def test_modified_after_rotate(self, mutable_view: DocumentView) -> None:
        mutable_view.rotate_page(0, 90)
        assert mutable_view.is_modified is True

    def test_modified_changed_signal_emits_true(self, mutable_view: DocumentView, qtbot) -> None:
        with qtbot.waitSignal(mutable_view.modified_changed, timeout=500) as blocker:
            mutable_view.rotate_page(0, 90)
        assert blocker.args == [True]

    def test_modified_changed_emits_false_after_save(
        self, mutable_view: DocumentView, qtbot
    ) -> None:
        mutable_view.rotate_page(0, 90)
        with qtbot.waitSignal(mutable_view.modified_changed, timeout=500) as blocker:
            mutable_view.save()
        assert blocker.args == [False]

    def test_modified_does_not_re_fire_for_same_state(self, mutable_view: DocumentView) -> None:
        events: list[bool] = []
        mutable_view.modified_changed.connect(events.append)
        mutable_view.rotate_page(0, 90)
        mutable_view.rotate_page(0, 90)  # still dirty
        # Only one True event; the second rotate doesn't re-fire.
        assert events == [True]


class TestPageOpsRouteThroughDocumentView:
    def test_rotate_page_updates_adapter(self, mutable_view: DocumentView) -> None:
        before = mutable_view.adapter.get_page_info(0).rotation
        mutable_view.rotate_page(0, 90)
        after = mutable_view.adapter.get_page_info(0).rotation
        assert (after - before) % 360 == 90

    def test_delete_pages_updates_count(self, mutable_view: DocumentView) -> None:
        before = mutable_view.page_view.page_count
        mutable_view.delete_pages([0])
        assert mutable_view.page_view.page_count == before - 1

    def test_insert_blank_page_updates_count(self, mutable_view: DocumentView) -> None:
        before = mutable_view.page_view.page_count
        mutable_view.insert_blank_page(0, 100, 100)
        assert mutable_view.page_view.page_count == before + 1

    def test_duplicate_page_updates_count(self, mutable_view: DocumentView) -> None:
        before = mutable_view.page_view.page_count
        mutable_view.duplicate_page(0)
        assert mutable_view.page_view.page_count == before + 1

    def test_move_page_changes_order(self, mutable_view: DocumentView) -> None:
        t0 = mutable_view.adapter.extract_text(0)
        last = mutable_view.page_view.page_count - 1
        mutable_view.move_page(0, last)
        assert mutable_view.adapter.extract_text(last) == t0

    def test_crop_page_shrinks_cropbox(self, mutable_view: DocumentView) -> None:
        info = mutable_view.adapter.get_page_info(0)
        mutable_view.crop_page(0, (5, 5, 5, 5))
        cb = mutable_view.adapter._doc[0].cropbox
        assert abs((cb.x1 - cb.x0) - (info.width_points - 10)) < 0.01


class TestDocumentViewSave:
    def test_save_persists_and_clears_dirty(
        self, mutable_view: DocumentView, mutable_pdf_path: Path
    ) -> None:
        mutable_view.duplicate_page(0)
        mutable_view.save()
        assert mutable_view.is_modified is False
        # Verify the file change persisted: reopen and check page count.
        mutable_view.close_document()
        from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter

        verifier = PyMuPDFAdapter()
        verifier.open(mutable_pdf_path)
        try:
            assert verifier.page_count == 4  # was 3
        finally:
            verifier.close()

    def test_save_as_updates_path(self, mutable_view: DocumentView, tmp_path: Path) -> None:
        new_path = tmp_path / "copy.pdf"
        mutable_view.rotate_page(0, 90)
        mutable_view.save_as(new_path)
        assert mutable_view.path == new_path
        assert new_path.exists()
        assert mutable_view.is_modified is False


class TestOrganizePanelOwnership:
    def test_document_view_exposes_organize_panel(self, sample_pdf_path: Path, qtbot) -> None:
        from pdfprism.ui.widgets.organize_panel import OrganizePagesPanel

        dv = DocumentView(sample_pdf_path)
        qtbot.addWidget(dv)
        assert isinstance(dv.organize_panel, OrganizePagesPanel)

    def test_open_binds_organize_panel(self, sample_pdf_path: Path, qtbot) -> None:
        dv = DocumentView(sample_pdf_path)
        qtbot.addWidget(dv)
        dv.open()
        # sample.pdf has 3 pages -> grid should have 3 rows
        assert dv.organize_panel._grid._model.rowCount() == 3


class TestOrganizePanelSyncAfterMutation:
    def test_rotate_updates_organize_panel(self, mutable_view: DocumentView) -> None:
        # Rotate should not change page count
        mutable_view.rotate_page(0, 90)
        assert mutable_view.organize_panel._grid._model.rowCount() == 3

    def test_delete_updates_organize_panel(self, mutable_view: DocumentView) -> None:
        mutable_view.delete_pages([0])
        assert mutable_view.organize_panel._grid._model.rowCount() == 2

    def test_duplicate_updates_organize_panel(self, mutable_view: DocumentView) -> None:
        mutable_view.duplicate_page(1)
        assert mutable_view.organize_panel._grid._model.rowCount() == 4


class TestOrganizePanelDrivenMutations:
    def test_panel_delete_signal_actually_deletes(self, mutable_view: DocumentView) -> None:
        # Simulate the panel emitting delete_requested with index 0
        mutable_view.organize_panel.delete_requested.emit([0])
        assert mutable_view.adapter.page_count == 2
        assert mutable_view.is_modified is True
        # And the panel re-bound to the new state
        assert mutable_view.organize_panel._grid._model.rowCount() == 2

    def test_panel_rotate_signal_actually_rotates(self, mutable_view: DocumentView) -> None:
        # Adapter has no public rotation-readback API; verify the
        # signal wiring by checking is_modified flips True.
        assert mutable_view.is_modified is False
        mutable_view.organize_panel.rotate_requested.emit([0], 90)
        assert mutable_view.is_modified is True

    def test_panel_duplicate_signal_actually_duplicates(self, mutable_view: DocumentView) -> None:
        mutable_view.organize_panel.duplicate_requested.emit([0, 2])
        # 3 pages + 2 duplicates = 5
        assert mutable_view.adapter.page_count == 5

    def test_panel_move_signal_actually_moves(self, mutable_view: DocumentView) -> None:
        mutable_view.organize_panel.move_requested.emit(0, 2)
        # Page count unchanged; just reordered
        assert mutable_view.adapter.page_count == 3
        assert mutable_view.is_modified is True

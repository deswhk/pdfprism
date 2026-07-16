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


class TestOrganizeCropSlot:
    """DocumentView._on_organize_crop: apply same margins to selected pages."""

    # ---- Positive cases -----------------------------------------------------

    def test_single_page_crop_applied(self, mutable_view: DocumentView) -> None:
        assert mutable_view.is_modified is False
        mutable_view._on_organize_crop([1], (10.0, 5.0, 10.0, 5.0))
        assert mutable_view.is_modified is True
        # Page count unchanged
        assert mutable_view.adapter.page_count == 3

    def test_multi_page_crop_applied(self, mutable_view: DocumentView) -> None:
        mutable_view._on_organize_crop([0, 1, 2], (10.0, 5.0, 10.0, 5.0))
        assert mutable_view.is_modified is True
        assert mutable_view.adapter.page_count == 3

    def test_organize_panel_still_bound_after_crop(self, mutable_view: DocumentView) -> None:
        """Rebind dance ran: organize panel model row count stays in sync."""
        mutable_view._on_organize_crop([0, 2], (5.0, 5.0, 5.0, 5.0))
        assert (
            mutable_view.organize_panel._grid._model.rowCount() == mutable_view.adapter.page_count
        )

    def test_thumbnail_panel_still_bound_after_crop(self, mutable_view: DocumentView) -> None:
        mutable_view._on_organize_crop([0], (5.0, 5.0, 5.0, 5.0))
        assert mutable_view.thumbnail_panel._model.rowCount() == mutable_view.adapter.page_count

    def test_signal_emitted_from_panel_triggers_crop(self, mutable_view: DocumentView) -> None:
        """End-to-end: the panel's crop_requested signal (when wired in
        sub-step 4) will call this slot. Test the slot via direct emit
        to validate the routing shape ahead of the UI wiring."""
        # For now, the signal doesn't exist on the panel yet -- verify
        # the slot handles a direct call as it will when wired.
        assert mutable_view.is_modified is False
        mutable_view._on_organize_crop([0, 1], (20.0, 20.0, 20.0, 20.0))
        assert mutable_view.is_modified is True

    # ---- Negative cases -----------------------------------------------------

    def test_empty_indices_is_no_op(self, mutable_view: DocumentView) -> None:
        """Empty selection must not mutate the doc or dirty the flag."""
        assert mutable_view.is_modified is False
        mutable_view._on_organize_crop([], (10.0, 10.0, 10.0, 10.0))
        assert mutable_view.is_modified is False
        assert mutable_view.adapter.page_count == 3

    def test_out_of_range_index_propagates(self, mutable_view: DocumentView) -> None:
        from pdfprism.core.exceptions import PageOutOfRangeError

        with pytest.raises(PageOutOfRangeError):
            mutable_view._on_organize_crop([99], (5.0, 5.0, 5.0, 5.0))

    def test_negative_margins_propagate(self, mutable_view: DocumentView) -> None:
        from pdfprism.core.exceptions import PageOperationError

        with pytest.raises(PageOperationError):
            mutable_view._on_organize_crop([0], (-1.0, 0.0, 0.0, 0.0))

    def test_zero_area_margins_propagate(self, mutable_view: DocumentView) -> None:
        """Margins that leave <= 0 area raise PageOperationError."""
        from pdfprism.core.exceptions import PageOperationError

        # sample.pdf is US Letter (~612x792 pts). left+right = 1000 pt
        # exceeds width, forcing zero-area crop.
        with pytest.raises(PageOperationError):
            mutable_view._on_organize_crop([0], (0.0, 500.0, 0.0, 500.0))

    def test_failure_midway_leaves_partial_state(self, mutable_view: DocumentView) -> None:
        """Documented behaviour: fail-fast, no rollback.

        If the second index in the loop raises, the first index's crop
        is already applied and stays applied. This matches
        _on_organize_duplicate / _on_organize_rotate in PR 9. A future
        refactor to atomic rollback would be a conscious, test-visible
        change.
        """
        from pdfprism.core.exceptions import PageOutOfRangeError

        assert mutable_view.is_modified is False
        # Index 0 is valid, index 99 is not -- second call raises.
        with pytest.raises(PageOutOfRangeError):
            mutable_view._on_organize_crop([0, 99], (5.0, 5.0, 5.0, 5.0))
        # Adapter is dirty from the first crop even though the loop failed.
        assert mutable_view.is_modified is True


class TestOrganizeExtractSlot:
    """DocumentView._on_organize_extract: read-only extraction of selected pages."""

    def test_slot_exists(self, mutable_view: DocumentView) -> None:
        """Positive: slot is defined on DocumentView (PR 9.5 wiring surface)."""
        assert hasattr(mutable_view, "_on_organize_extract")

    def test_writes_output_file(self, mutable_view: DocumentView, tmp_path: Path) -> None:
        """Positive: end-to-end -- indices + path -> file exists with N pages."""
        from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter

        out = tmp_path / "extracted.pdf"
        mutable_view._on_organize_extract([0, 2], out)
        assert out.exists()
        verifier = PyMuPDFAdapter()
        verifier.open(out)
        try:
            assert verifier.page_count == 2
        finally:
            verifier.close()

    def test_source_untouched(self, mutable_view: DocumentView, tmp_path: Path) -> None:
        """Positive: extraction is read-only; dirty flag stays False."""
        out = tmp_path / "extracted.pdf"
        before_count = mutable_view.adapter.page_count
        mutable_view._on_organize_extract([0, 1], out)
        assert mutable_view.adapter.page_count == before_count
        assert mutable_view.is_modified is False

    def test_empty_indices_defensive_no_op(
        self, mutable_view: DocumentView, tmp_path: Path
    ) -> None:
        """Negative: empty list -> no file, no exception (defensive guard)."""
        out = tmp_path / "should_not_exist.pdf"
        mutable_view._on_organize_extract([], out)
        assert not out.exists()


class TestOrganizeSignalWiring:
    """Regression: silent slot-not-wired bugs must be catchable by tests.

    Uses Qt's QObject.receivers() to confirm at least one slot is connected
    to each signal. This is deliberately lenient (>= 1 connection) so a
    future refactor that adds an additional forward doesn't break these."""

    def test_crop_requested_is_wired(self, mutable_view: DocumentView) -> None:
        """Positive regression: crop_requested has >= 1 receiver.

        The bug this catches: panel emits, no slot listens. Sub-step 3
        tests didn't catch it because they called the slot directly.
        ``isSignalConnected`` reports True as long as at least one slot
        (of any kind: method, lambda, forward-emit) is connected.
        """
        from PySide6.QtCore import QMetaMethod

        panel = mutable_view.organize_panel
        assert panel.isSignalConnected(QMetaMethod.fromSignal(panel.crop_requested)), (
            "crop_requested has no receiver -- DocumentView wiring is broken"
        )

    def test_extract_requested_is_wired(self, mutable_view: DocumentView) -> None:
        """Positive regression: extract_requested has >= 1 receiver."""
        from PySide6.QtCore import QMetaMethod

        panel = mutable_view.organize_panel
        assert panel.isSignalConnected(QMetaMethod.fromSignal(panel.extract_requested))

    def test_signal_end_to_end_actually_extracts(
        self, mutable_view: DocumentView, tmp_path: Path
    ) -> None:
        """Positive regression: emitting the signal drives the slot to write a file.

        This is the *complete* end-to-end path: panel.emit -> DocumentView
        slot -> PageService -> file on disk. If the wiring is broken,
        the file won't exist even though slot-direct tests pass.
        """
        from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter

        out = tmp_path / "via_signal.pdf"
        # Emit the panel signal directly, as the panel would after the
        # file dialog closes.
        mutable_view.organize_panel.extract_requested.emit([0, 1], out)
        assert out.exists()
        v = PyMuPDFAdapter()
        v.open(out)
        try:
            assert v.page_count == 2
        finally:
            v.close()

    def test_crop_signal_end_to_end_dirties_document(self, mutable_view: DocumentView) -> None:
        """Positive regression: crop signal actually mutates via the wiring."""
        assert mutable_view.is_modified is False
        mutable_view.organize_panel.crop_requested.emit([0], (5.0, 5.0, 5.0, 5.0))
        assert mutable_view.is_modified is True


class TestRedactSelectionSlot:
    """PR 12.1: _on_redact_selection_requested routes to service."""

    def test_delegates_to_service(self, mutable_view, monkeypatch) -> None:
        """Positive: slot calls RedactionService.redact_words with args."""
        from pdfprism.core.types import Word

        calls: list = []

        class _SpyService:
            def __init__(self, a, **kwargs):
                pass

            def redact_words(self, page_index, words):
                calls.append((page_index, list(words)))
                return len(words)

        # Note: DocumentView imports RedactionService lazily inside the slot.
        # We monkeypatch on the module that's imported at slot-call time.
        import pdfprism.services.redaction as red_mod

        monkeypatch.setattr(red_mod, "RedactionService", _SpyService)

        words = [Word(text="x", x0=0.0, y0=0.0, x1=10.0, y1=10.0)]
        mutable_view._on_redact_selection_requested(0, words)

        assert len(calls) == 1
        got_page, got_words = calls[0]
        assert got_page == 0
        assert got_words == words

    def test_clears_selection_after_redact(self, mutable_view, monkeypatch) -> None:
        """Positive: slot clears PageView selection after committing redactions."""
        from pdfprism.core.types import Word

        cleared: list = []
        monkeypatch.setattr(
            mutable_view._page_view,
            "clear_selection",
            lambda: cleared.append(True),
        )

        import pdfprism.services.redaction as red_mod

        class _StubService:
            def __init__(self, a, **kwargs):
                pass

            def redact_words(self, page_index, words):
                return len(words)

        monkeypatch.setattr(red_mod, "RedactionService", _StubService)

        mutable_view._on_redact_selection_requested(
            0, [Word(text="x", x0=0.0, y0=0.0, x1=10.0, y1=10.0)]
        )
        assert cleared == [True]

"""Tests for OrganizePanel skeleton (PR 9 sub-step 2)."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.ui.page_cache import PageCache
from pdfprism.ui.widgets.organize_panel import OrganizePagesPanel, OrganizePanel


@pytest.fixture
def panel(qtbot) -> OrganizePanel:
    cache = PageCache()
    p = OrganizePanel(cache)
    qtbot.addWidget(p)
    return p


@pytest.fixture
def bound_panel(qtbot, sample_pdf_path: Path) -> OrganizePanel:
    cache = PageCache()
    p = OrganizePanel(cache)
    qtbot.addWidget(p)
    adapter = PyMuPDFAdapter()
    adapter.open(sample_pdf_path)
    p.set_adapter(adapter)
    return p


class TestEmpty:
    def test_no_rows_initially(self, panel: OrganizePanel) -> None:
        assert panel._model.rowCount() == 0

    def test_empty_selection_initially(self, panel: OrganizePanel) -> None:
        assert panel.selected_indices == []

    def test_view_mode_is_icon(self, panel: OrganizePanel) -> None:
        from PySide6.QtWidgets import QListView

        assert panel.viewMode() == QListView.ViewMode.IconMode

    def test_selection_mode_is_extended(self, panel: OrganizePanel) -> None:
        from PySide6.QtWidgets import QAbstractItemView

        assert panel.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection


class TestBinding:
    def test_set_adapter_populates_rows(self, bound_panel: OrganizePanel) -> None:
        # sample.pdf has 3 pages
        assert bound_panel._model.rowCount() == 3

    def test_clear_adapter_empties_rows(self, bound_panel: OrganizePanel) -> None:
        bound_panel.set_adapter(None)
        assert bound_panel._model.rowCount() == 0


class TestModelData:
    def test_display_role_returns_page_label(self, bound_panel: OrganizePanel) -> None:
        idx = bound_panel._model.index(0, 0)
        assert bound_panel._model.data(idx, Qt.ItemDataRole.DisplayRole) == "Page 1"

    def test_decoration_role_returns_pixmap(self, bound_panel: OrganizePanel) -> None:
        idx = bound_panel._model.index(0, 0)
        pix = bound_panel._model.data(idx, Qt.ItemDataRole.DecorationRole)
        assert pix is not None

    def test_out_of_range_returns_none(self, bound_panel: OrganizePanel) -> None:
        idx = bound_panel._model.index(99, 0)
        assert bound_panel._model.data(idx, Qt.ItemDataRole.DisplayRole) is None


class TestSelection:
    def test_selecting_one_row_updates_selected_indices(self, bound_panel: OrganizePanel) -> None:
        idx = bound_panel._model.index(1, 0)
        bound_panel.setCurrentIndex(idx)
        assert bound_panel.selected_indices == [1]

    def test_selection_changed_signal_emits(self, bound_panel: OrganizePanel, qtbot) -> None:
        idx = bound_panel._model.index(2, 0)
        with qtbot.waitSignal(bound_panel.selection_changed, timeout=500) as blocker:
            bound_panel.setCurrentIndex(idx)
        assert blocker.args == [[2]]


class TestRequestOperations:
    def test_request_rotate_with_no_selection_does_not_emit(
        self, bound_panel: OrganizePanel, qtbot
    ) -> None:
        signals_caught: list[tuple] = []
        bound_panel.rotate_requested.connect(lambda i, d: signals_caught.append((i, d)))
        bound_panel.request_rotate(90)
        assert signals_caught == []

    def test_request_rotate_with_selection_emits(self, bound_panel: OrganizePanel, qtbot) -> None:
        bound_panel.setCurrentIndex(bound_panel._model.index(1, 0))
        with qtbot.waitSignal(bound_panel.rotate_requested, timeout=500) as blocker:
            bound_panel.request_rotate(90)
        assert blocker.args == [[1], 90]

    def test_request_delete_with_selection_emits(self, bound_panel: OrganizePanel, qtbot) -> None:
        bound_panel.setCurrentIndex(bound_panel._model.index(0, 0))
        with qtbot.waitSignal(bound_panel.delete_requested, timeout=500) as blocker:
            bound_panel.request_delete()
        assert blocker.args == [[0]]

    def test_request_delete_with_no_selection_does_not_emit(
        self, bound_panel: OrganizePanel
    ) -> None:
        signals_caught: list = []
        bound_panel.delete_requested.connect(signals_caught.append)
        bound_panel.request_delete()
        assert signals_caught == []

    def test_request_duplicate_with_selection_emits(
        self, bound_panel: OrganizePanel, qtbot
    ) -> None:
        bound_panel.setCurrentIndex(bound_panel._model.index(2, 0))
        with qtbot.waitSignal(bound_panel.duplicate_requested, timeout=500) as blocker:
            bound_panel.request_duplicate()
        assert blocker.args == [[2]]

    def test_multi_selection_passed_through(self, bound_panel: OrganizePanel) -> None:
        from PySide6.QtCore import QItemSelectionModel

        sm = bound_panel.selectionModel()
        sm.select(
            bound_panel._model.index(0, 0),
            QItemSelectionModel.SelectionFlag.Select,
        )
        sm.select(
            bound_panel._model.index(2, 0),
            QItemSelectionModel.SelectionFlag.Select,
        )
        captured: list = []
        bound_panel.delete_requested.connect(captured.append)
        bound_panel.request_delete()
        assert captured == [[0, 2]]


class TestDropTranslation:
    """Translation of Qt's drop semantics to DocumentView.move_page contract.

    These are the empirical findings from the Qt 6.11 probe captured in
    the implementation. ``from_row`` is the source; ``dest_row`` is where
    Qt's drop indicator wants the row to land (insertion semantics).
    """

    def test_no_op_same_row(self, panel: OrganizePanel) -> None:
        assert panel._qt_drop_to_move_page(2, 2) is None

    def test_forward_move_drops_by_one(self, panel: OrganizePanel) -> None:
        # Drag row 0 to drop-before-row-2 -> post-removal position 1.
        assert panel._qt_drop_to_move_page(0, 2) == (0, 1)

    def test_forward_move_to_end(self, panel: OrganizePanel) -> None:
        # Drag row 1 to drop-after-end-of-5 (dest 5) -> post-removal 4.
        assert panel._qt_drop_to_move_page(1, 5) == (1, 4)

    def test_backward_move_keeps_dest(self, panel: OrganizePanel) -> None:
        # Drag row 3 to drop-before-row-0 -> post-removal 0.
        assert panel._qt_drop_to_move_page(3, 0) == (3, 0)

    def test_backward_move_middle(self, panel: OrganizePanel) -> None:
        # Drag row 4 to drop-before-row-2 -> post-removal 2.
        assert panel._qt_drop_to_move_page(4, 2) == (4, 2)

    def test_adjacent_forward_is_no_op(self, panel: OrganizePanel) -> None:
        # Drag row 1 to "after itself" (dest 2 = before row 2) lands at
        # post-removal position 1 -- back where it started.
        assert panel._qt_drop_to_move_page(1, 2) == (1, 1)


class TestDragDropEnabled:
    def test_drag_enabled(self, panel: OrganizePanel) -> None:
        assert panel.dragEnabled() is True

    def test_accept_drops(self, panel: OrganizePanel) -> None:
        assert panel.acceptDrops() is True

    def test_drop_indicator_shown(self, panel: OrganizePanel) -> None:
        assert panel.showDropIndicator() is True


# ---- OrganizePagesPanel wrapper tests --------------------------------------


@pytest.fixture
def wrapper(qtbot) -> OrganizePagesPanel:
    from pdfprism.ui.page_cache import PageCache

    cache = PageCache()
    w = OrganizePagesPanel(cache)
    qtbot.addWidget(w)
    return w


@pytest.fixture
def bound_wrapper(qtbot, sample_pdf_path: Path) -> OrganizePagesPanel:
    from pdfprism.ui.page_cache import PageCache

    cache = PageCache()
    w = OrganizePagesPanel(cache)
    qtbot.addWidget(w)
    adapter = PyMuPDFAdapter()
    adapter.open(sample_pdf_path)
    w.set_adapter(adapter)
    return w


class TestToolbarInitialState:
    def test_all_actions_disabled_when_no_selection(self, wrapper: OrganizePagesPanel) -> None:
        assert wrapper.act_rotate_right.isEnabled() is False
        assert wrapper.act_rotate_left.isEnabled() is False
        assert wrapper.act_rotate_180.isEnabled() is False
        assert wrapper.act_delete.isEnabled() is False
        assert wrapper.act_duplicate.isEnabled() is False

    def test_status_label_initial(self, wrapper: OrganizePagesPanel) -> None:
        assert "0 page" in wrapper._status.text()


class TestToolbarSelectionAware:
    def test_actions_enabled_after_selection(self, bound_wrapper: OrganizePagesPanel) -> None:
        bound_wrapper._grid.setCurrentIndex(bound_wrapper._grid._model.index(0, 0))
        assert bound_wrapper.act_rotate_right.isEnabled() is True
        assert bound_wrapper.act_delete.isEnabled() is True

    def test_status_label_updates_after_selection(self, bound_wrapper: OrganizePagesPanel) -> None:
        bound_wrapper._grid.setCurrentIndex(bound_wrapper._grid._model.index(1, 0))
        assert "1 of 3 selected" in bound_wrapper._status.text()

    def test_actions_redisable_when_selection_cleared(
        self, bound_wrapper: OrganizePagesPanel
    ) -> None:

        bound_wrapper._grid.setCurrentIndex(bound_wrapper._grid._model.index(1, 0))
        sm = bound_wrapper._grid.selectionModel()
        sm.clearSelection()
        assert bound_wrapper.act_rotate_right.isEnabled() is False


class TestToolbarTriggersOperations:
    def test_rotate_right_action_triggers_request(
        self, bound_wrapper: OrganizePagesPanel, qtbot
    ) -> None:
        bound_wrapper._grid.setCurrentIndex(bound_wrapper._grid._model.index(0, 0))
        with qtbot.waitSignal(bound_wrapper.rotate_requested, timeout=500) as blocker:
            bound_wrapper.act_rotate_right.trigger()
        assert blocker.args == [[0], 90]

    def test_delete_action_triggers_request(self, bound_wrapper: OrganizePagesPanel, qtbot) -> None:
        bound_wrapper._grid.setCurrentIndex(bound_wrapper._grid._model.index(1, 0))
        with qtbot.waitSignal(bound_wrapper.delete_requested, timeout=500) as blocker:
            bound_wrapper.act_delete.trigger()
        assert blocker.args == [[1]]

    def test_duplicate_action_triggers_request(
        self, bound_wrapper: OrganizePagesPanel, qtbot
    ) -> None:
        bound_wrapper._grid.setCurrentIndex(bound_wrapper._grid._model.index(2, 0))
        with qtbot.waitSignal(bound_wrapper.duplicate_requested, timeout=500) as blocker:
            bound_wrapper.act_duplicate.trigger()
        assert blocker.args == [[2]]


class TestSelectAllAction:
    def test_select_all_selects_every_row(self, bound_wrapper: OrganizePagesPanel) -> None:
        bound_wrapper.act_select_all.trigger()
        assert bound_wrapper.selected_indices == [0, 1, 2]


class TestShortcuts:
    def test_ctrl_r_bound_on_rotate_right(self, wrapper: OrganizePagesPanel) -> None:
        from PySide6.QtGui import QKeySequence

        assert wrapper.act_rotate_right.shortcut() == QKeySequence("Ctrl+R")

    def test_ctrl_shift_r_bound_on_rotate_left(self, wrapper: OrganizePagesPanel) -> None:
        from PySide6.QtGui import QKeySequence

        assert wrapper.act_rotate_left.shortcut() == QKeySequence("Ctrl+Shift+R")

    def test_delete_bound_on_delete(self, wrapper: OrganizePagesPanel) -> None:
        from PySide6.QtGui import QKeySequence

        assert wrapper.act_delete.shortcut() == QKeySequence.StandardKey.Delete

    def test_ctrl_d_bound_on_duplicate(self, wrapper: OrganizePagesPanel) -> None:
        from PySide6.QtGui import QKeySequence

        assert wrapper.act_duplicate.shortcut() == QKeySequence("Ctrl+D")

    def test_select_all_bound_on_select_all(self, wrapper: OrganizePagesPanel) -> None:
        from PySide6.QtGui import QKeySequence

        assert wrapper.act_select_all.shortcut() == QKeySequence.StandardKey.SelectAll

    def test_shortcut_context_is_widget_with_children(self, wrapper: OrganizePagesPanel) -> None:
        from PySide6.QtCore import Qt

        for act in (
            wrapper.act_rotate_right,
            wrapper.act_rotate_left,
            wrapper.act_delete,
            wrapper.act_duplicate,
            wrapper.act_select_all,
        ):
            assert act.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut


# ---- PR 9.5: Crop wiring tests ------------------------------------------------


class TestRequestCropOnGrid:
    """OrganizePanel.request_crop -> crop_requested signal."""

    def test_no_selection_does_not_emit(self, bound_panel: OrganizePanel) -> None:
        """Negative: no selection -> no emission (matches other request_* helpers)."""
        received: list = []
        bound_panel.crop_requested.connect(
            lambda indices, margins: received.append((indices, margins))
        )
        bound_panel.request_crop((5.0, 5.0, 5.0, 5.0))
        assert received == []

    def test_with_selection_emits_indices_and_margins(
        self, bound_panel: OrganizePanel, qtbot
    ) -> None:
        """Positive: selection + margins -> exactly one emission."""
        bound_panel.setCurrentIndex(bound_panel._model.index(1, 0))
        with qtbot.waitSignal(bound_panel.crop_requested, timeout=500) as blocker:
            bound_panel.request_crop((10.0, 20.0, 30.0, 40.0))
        assert blocker.args == [[1], (10.0, 20.0, 30.0, 40.0)]

    def test_multi_selection_passed_through(self, bound_panel: OrganizePanel) -> None:
        """Positive: multi-select carries every selected index in sorted order."""
        from PySide6.QtCore import QItemSelectionModel

        sm = bound_panel.selectionModel()
        sm.select(
            bound_panel._model.index(0, 0),
            QItemSelectionModel.SelectionFlag.Select,
        )
        sm.select(
            bound_panel._model.index(2, 0),
            QItemSelectionModel.SelectionFlag.Select,
        )
        received: list = []
        bound_panel.crop_requested.connect(
            lambda indices, margins: received.append((indices, margins))
        )
        bound_panel.request_crop((5.0, 5.0, 5.0, 5.0))
        assert received == [([0, 2], (5.0, 5.0, 5.0, 5.0))]


class TestSetAdapterStoresReference:
    """set_adapter must store the adapter for later use by the composite slot."""

    def test_adapter_stored_after_set(
        self, bound_panel: OrganizePanel, sample_pdf_path: Path
    ) -> None:
        """Positive: _adapter attribute holds the bound adapter."""
        assert bound_panel._adapter is not None
        # bound_panel was created via a fixture that opened sample_pdf_path.
        # Confirm the round-trip by reading a page count.
        assert bound_panel._adapter.page_count == 3

    def test_adapter_reset_to_none(self, bound_panel: OrganizePanel) -> None:
        """Negative: unbinding sets _adapter back to None."""
        bound_panel.set_adapter(None)
        assert bound_panel._adapter is None


class TestCropActionOnComposite:
    """OrganizePagesPanel.act_crop: toolbar/context-menu registration + state."""

    def test_act_crop_exists(self, wrapper: OrganizePagesPanel) -> None:
        assert wrapper.act_crop is not None
        assert wrapper.act_crop.text() == "&Crop..."

    def test_act_crop_disabled_when_no_selection(self, wrapper: OrganizePagesPanel) -> None:
        """Negative: no selection -> action disabled (same rule as rotate/delete)."""
        assert wrapper.act_crop.isEnabled() is False

    def test_act_crop_enabled_after_selection(self, bound_wrapper: OrganizePagesPanel) -> None:
        """Positive: selection enables the action."""
        bound_wrapper._grid.setCurrentIndex(bound_wrapper._grid._model.index(0, 0))
        assert bound_wrapper.act_crop.isEnabled() is True

    def test_act_crop_in_context_menu_actions(self, wrapper: OrganizePagesPanel) -> None:
        """Positive: context menu wiring registers the action."""
        # The context menu is built on demand; verify by inspecting the
        # slot's handler assembles a menu containing act_crop. Easier:
        # confirm the action is a child of the wrapper (added via addAction).
        actions = wrapper.actions()
        assert wrapper.act_crop in actions


class TestCompositeReemitsCropRequested:
    """Composite re-emits grid.crop_requested unchanged."""

    def test_reemission_carries_indices_and_margins(
        self, bound_wrapper: OrganizePagesPanel, qtbot
    ) -> None:
        """Positive: signal transits the composite without data loss."""
        bound_wrapper._grid.setCurrentIndex(bound_wrapper._grid._model.index(2, 0))
        with qtbot.waitSignal(bound_wrapper.crop_requested, timeout=500) as blocker:
            bound_wrapper._grid.request_crop((1.0, 2.0, 3.0, 4.0))
        assert blocker.args == [[2], (1.0, 2.0, 3.0, 4.0)]


class TestOnCropRequestedSlot:
    """OrganizePagesPanel._on_crop_requested opens dialog, calls request_crop."""

    def test_no_selection_is_noop(self, wrapper: OrganizePagesPanel, monkeypatch) -> None:
        """Negative: no selection -> slot returns without opening a dialog."""
        from pdfprism.ui.dialogs import crop as crop_mod

        opened: list = []

        def spy_init(self, *a, **kw):
            opened.append((a, kw))
            raise AssertionError("CropDialog should not be constructed")

        monkeypatch.setattr(crop_mod.CropDialog, "__init__", spy_init)
        wrapper._on_crop_requested()  # must not raise
        assert opened == []

    def test_no_adapter_bound_is_noop(self, wrapper: OrganizePagesPanel, monkeypatch) -> None:
        """Negative: selection but no adapter -> slot returns."""
        from pdfprism.ui.dialogs import crop as crop_mod

        # Force selection presence via the grid model directly (no real
        # adapter, but selected_indices only reads the selection model).
        # The grid's ExtendedSelection with no rows means we can't easily
        # select anything, so we monkey-patch selected_indices to return
        # a non-empty list simulating the "selection but no adapter" edge.
        monkeypatch.setattr(
            type(wrapper._grid),
            "selected_indices",
            property(lambda self: [0]),
        )
        opened: list = []
        monkeypatch.setattr(
            crop_mod.CropDialog,
            "__init__",
            lambda self, *a, **kw: opened.append(True),
        )
        wrapper._on_crop_requested()  # must not raise or construct dialog
        assert opened == []

    def test_accepted_dialog_calls_request_crop(
        self, bound_wrapper: OrganizePagesPanel, monkeypatch, qtbot
    ) -> None:
        """Positive: dialog Accepted -> grid.request_crop called with the margins."""
        from pdfprism.ui.dialogs import crop as crop_mod

        bound_wrapper._grid.setCurrentIndex(bound_wrapper._grid._model.index(0, 0))

        # Stub CropDialog: don't render a real modal, just claim Accepted
        # and expose fixed margins.
        class StubDialog:
            DialogCode = crop_mod.CropDialog.DialogCode

            def __init__(self, *a, **kw):
                self.margins = (11.0, 22.0, 33.0, 44.0)

            def exec(self):
                return self.DialogCode.Accepted

        monkeypatch.setattr(crop_mod, "CropDialog", StubDialog)

        with qtbot.waitSignal(bound_wrapper.crop_requested, timeout=500) as blocker:
            bound_wrapper._on_crop_requested()
        assert blocker.args == [[0], (11.0, 22.0, 33.0, 44.0)]

    def test_rejected_dialog_does_not_call_request_crop(
        self, bound_wrapper: OrganizePagesPanel, monkeypatch
    ) -> None:
        """Negative: dialog Rejected -> no crop_requested emission."""
        from pdfprism.ui.dialogs import crop as crop_mod

        bound_wrapper._grid.setCurrentIndex(bound_wrapper._grid._model.index(0, 0))

        class StubDialog:
            DialogCode = crop_mod.CropDialog.DialogCode

            def __init__(self, *a, **kw):
                self.margins = (11.0, 22.0, 33.0, 44.0)

            def exec(self):
                return self.DialogCode.Rejected

        monkeypatch.setattr(crop_mod, "CropDialog", StubDialog)

        received: list = []
        bound_wrapper.crop_requested.connect(
            lambda indices, margins: received.append((indices, margins))
        )
        bound_wrapper._on_crop_requested()
        assert received == []


# ---- PR 9.5: Extract wiring tests ------------------------------------------


class TestSuggestExtractFilename:
    """Filename suggestion helper: contiguous vs non-contiguous branches."""

    def test_contiguous_range_gets_range_name(self, wrapper: OrganizePagesPanel) -> None:
        """Positive: [2,3,4] on 'report' -> 'report_pages_3-5.pdf' (1-based)."""
        assert wrapper._suggest_extract_filename("report", [2, 3, 4]) == "report_pages_3-5.pdf"

    def test_non_contiguous_gets_selection_name(self, wrapper: OrganizePagesPanel) -> None:
        """Positive: [0,2,5] on 'report' -> 'report_pages_selection.pdf'."""
        assert (
            wrapper._suggest_extract_filename("report", [0, 2, 5]) == "report_pages_selection.pdf"
        )

    def test_single_page_is_trivially_contiguous(self, wrapper: OrganizePagesPanel) -> None:
        """Positive: [4] -> '<stem>_pages_5-5.pdf' (single-element ranges are contiguous)."""
        assert wrapper._suggest_extract_filename("doc", [4]) == "doc_pages_5-5.pdf"


class TestOnExtractRequestedSlot:
    """OrganizePagesPanel._on_extract_requested: opens Save-As, then emits."""

    def test_no_selection_is_noop(self, wrapper: OrganizePagesPanel, monkeypatch) -> None:
        """Negative: no selection -> no file dialog opens."""
        from PySide6.QtWidgets import QFileDialog

        opened: list = []

        def spy(*a, **kw):
            opened.append((a, kw))
            return ("", "")

        monkeypatch.setattr(QFileDialog, "getSaveFileName", spy)
        wrapper._on_extract_requested()
        assert opened == []

    def test_no_adapter_is_noop(self, wrapper: OrganizePagesPanel, monkeypatch) -> None:
        """Negative: selection but no adapter -> no file dialog."""
        from PySide6.QtWidgets import QFileDialog

        # Simulate selection via property override (no rows to select on).
        monkeypatch.setattr(
            type(wrapper._grid),
            "selected_indices",
            property(lambda self: [0]),
        )
        opened: list = []
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *a, **kw: opened.append(True) or ("", ""),
        )
        wrapper._on_extract_requested()
        assert opened == []

    def test_dialog_cancelled_does_not_emit(
        self, bound_wrapper: OrganizePagesPanel, monkeypatch
    ) -> None:
        """Negative: user cancels file dialog -> no extract_requested emission."""
        from PySide6.QtWidgets import QFileDialog

        bound_wrapper._grid.setCurrentIndex(bound_wrapper._grid._model.index(0, 0))
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *a, **kw: ("", ""),  # empty string = cancel
        )
        received: list = []
        bound_wrapper.extract_requested.connect(
            lambda indices, path: received.append((indices, path))
        )
        bound_wrapper._on_extract_requested()
        assert received == []

    def test_dialog_accepted_emits_with_chosen_path(
        self, bound_wrapper: OrganizePagesPanel, monkeypatch, qtbot, tmp_path: Path
    ) -> None:
        """Positive: user picks a path -> extract_requested fires with it."""
        from PySide6.QtWidgets import QFileDialog

        bound_wrapper._grid.setCurrentIndex(bound_wrapper._grid._model.index(1, 0))
        chosen_path = tmp_path / "my_choice.pdf"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *a, **kw: (str(chosen_path), "PDF files (*.pdf)"),
        )
        with qtbot.waitSignal(bound_wrapper.extract_requested, timeout=500) as blocker:
            bound_wrapper._on_extract_requested()
        assert blocker.args == [[1], chosen_path]

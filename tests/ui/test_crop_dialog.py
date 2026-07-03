"""Tests for CropDialog."""

from pathlib import Path

import pytest

from pdfprism.ui.dialogs.crop import CropDialog


@pytest.fixture
def dialog(qtbot) -> CropDialog:
    dlg = CropDialog(page_index=0, page_width=612, page_height=792)
    qtbot.addWidget(dlg)
    return dlg


class TestDefaults:
    def test_default_margins_are_zero(self, dialog: CropDialog) -> None:
        assert dialog.margins == (0.0, 0.0, 0.0, 0.0)

    def test_initial_margins_respected(self, qtbot) -> None:
        dlg = CropDialog(
            page_index=0,
            page_width=612,
            page_height=792,
            initial_margins=(10, 20, 30, 40),
        )
        qtbot.addWidget(dlg)
        assert dlg.margins == (10.0, 20.0, 30.0, 40.0)


class TestSpinboxRanges:
    def test_top_bottom_capped_by_height(self, dialog: CropDialog) -> None:
        # Range upper bound is dim - 1
        assert dialog._top.maximum() == pytest.approx(791.0)
        assert dialog._bottom.maximum() == pytest.approx(791.0)

    def test_left_right_capped_by_width(self, dialog: CropDialog) -> None:
        assert dialog._left.maximum() == pytest.approx(611.0)
        assert dialog._right.maximum() == pytest.approx(611.0)


class TestReset:
    def test_reset_zeros_all_fields(self, dialog: CropDialog) -> None:
        dialog._top.setValue(50)
        dialog._right.setValue(50)
        dialog._bottom.setValue(50)
        dialog._left.setValue(50)
        dialog._reset()
        assert dialog.margins == (0.0, 0.0, 0.0, 0.0)


class TestMarginsOrder:
    def test_margins_order_is_top_right_bottom_left(self, dialog: CropDialog) -> None:
        dialog._top.setValue(1)
        dialog._right.setValue(2)
        dialog._bottom.setValue(3)
        dialog._left.setValue(4)
        assert dialog.margins == (1.0, 2.0, 3.0, 4.0)


class TestTitle:
    def test_title_uses_one_based_page(self, qtbot) -> None:
        dlg = CropDialog(page_index=4, page_width=612, page_height=792)
        qtbot.addWidget(dlg)
        # 0-based 4 -> 1-based "Page 5"
        assert "5" in dlg.windowTitle()


# ---- PR 9.5: CropPreview widget + preview integration --------------------


@pytest.fixture
def blank_pixmap(qtbot):
    """Simple 100x150 pixmap for CropPreview tests (no adapter required)."""
    from PySide6.QtGui import QColor, QPixmap

    pix = QPixmap(100, 150)
    pix.fill(QColor("white"))
    return pix


class TestCropPreviewWidget:
    """Direct tests of the CropPreview widget in isolation."""

    def test_construct_with_pixmap_sets_fixed_size(self, blank_pixmap, qtbot) -> None:
        from pdfprism.ui.dialogs.crop import CropPreview

        preview = CropPreview(blank_pixmap, page_width=200.0, page_height=300.0)
        qtbot.addWidget(preview)
        # Pixmap is 100x150 and already fits within the preview budget;
        # scaling preserves size when input <= max.
        assert preview.size() == blank_pixmap.size()

    def test_scales_oversize_pixmap_to_fit_budget(self, qtbot) -> None:
        from PySide6.QtGui import QColor, QPixmap

        from pdfprism.ui.dialogs.crop import CropPreview

        # 1000x2000 pixmap should be scaled down; aspect ratio (1:2)
        # preserved; must fit within (280, 360).
        big = QPixmap(1000, 2000)
        big.fill(QColor("white"))
        preview = CropPreview(big, page_width=1000.0, page_height=2000.0)
        qtbot.addWidget(preview)
        assert preview.width() <= 280
        assert preview.height() <= 360
        # Aspect ratio preserved (with some rounding tolerance).
        ratio = preview.width() / preview.height()
        assert abs(ratio - 0.5) < 0.02

    def test_zero_margins_retained_rect_is_full_pixmap(self, blank_pixmap, qtbot) -> None:
        from pdfprism.ui.dialogs.crop import CropPreview

        preview = CropPreview(blank_pixmap, page_width=200.0, page_height=300.0)
        qtbot.addWidget(preview)
        preview.set_margins((0.0, 0.0, 0.0, 0.0))
        rect = preview._retained_rect()
        assert rect.x() == 0
        assert rect.y() == 0
        assert rect.width() == blank_pixmap.width()
        assert rect.height() == blank_pixmap.height()

    def test_symmetric_margins_produce_centred_interior(self, blank_pixmap, qtbot) -> None:
        from pdfprism.ui.dialogs.crop import CropPreview

        # page 200x300 pts, pixmap 100x150 px -> scale 0.5 px/pt.
        # 20-pt margin on all sides -> 10-px inset all round.
        preview = CropPreview(blank_pixmap, page_width=200.0, page_height=300.0)
        qtbot.addWidget(preview)
        preview.set_margins((20.0, 20.0, 20.0, 20.0))
        rect = preview._retained_rect()
        assert rect.x() == 10
        assert rect.y() == 10
        assert rect.width() == blank_pixmap.width() - 20
        assert rect.height() == blank_pixmap.height() - 20

    def test_asymmetric_margins_shift_interior(self, blank_pixmap, qtbot) -> None:
        from pdfprism.ui.dialogs.crop import CropPreview

        # Only left = 40 pt (20 px), only top = 60 pt (30 px).
        preview = CropPreview(blank_pixmap, page_width=200.0, page_height=300.0)
        qtbot.addWidget(preview)
        preview.set_margins((60.0, 0.0, 0.0, 40.0))
        rect = preview._retained_rect()
        assert rect.x() == 20
        assert rect.y() == 30
        assert rect.width() == blank_pixmap.width() - 20
        assert rect.height() == blank_pixmap.height() - 30

    def test_overcrop_clamps_geometry_to_non_negative(self, blank_pixmap, qtbot) -> None:
        """Negative case: margins that meet or exceed page dimensions."""
        from pdfprism.ui.dialogs.crop import CropPreview

        preview = CropPreview(blank_pixmap, page_width=200.0, page_height=300.0)
        qtbot.addWidget(preview)
        # left + right = 300 pt > page width 200 pt.
        preview.set_margins((0.0, 150.0, 0.0, 150.0))
        rect = preview._retained_rect()
        assert rect.width() == 0  # clamped, not negative
        assert rect.height() == blank_pixmap.height()

    def test_set_margins_triggers_repaint(self, blank_pixmap, qtbot) -> None:
        """update() is called; render to QImage differs before/after."""
        from PySide6.QtGui import QImage

        from pdfprism.ui.dialogs.crop import CropPreview

        preview = CropPreview(blank_pixmap, page_width=200.0, page_height=300.0)
        qtbot.addWidget(preview)
        preview.show()
        qtbot.waitExposed(preview)

        img_before = QImage(preview.size(), QImage.Format.Format_ARGB32)
        preview.render(img_before)
        preview.set_margins((30.0, 0.0, 0.0, 0.0))
        # Force repaint synchronously so the render captures the new state.
        preview.repaint()
        img_after = QImage(preview.size(), QImage.Format.Format_ARGB32)
        preview.render(img_after)
        assert img_before != img_after


class TestCropDialogPreviewIntegration:
    """CropDialog now wires spinbox changes into the preview live."""

    def test_no_page_cache_degrades_to_form_only(self, qtbot) -> None:
        """PR 8 backward-compat: dialog constructs and works without a cache."""
        from pdfprism.ui.dialogs.crop import CropDialog

        dlg = CropDialog(
            page_index=0,
            page_width=200.0,
            page_height=300.0,
        )
        qtbot.addWidget(dlg)
        assert dlg._preview is None
        # Public contract intact: margins property still works.
        assert dlg.margins == (0.0, 0.0, 0.0, 0.0)

    def test_preview_created_when_cache_provided(self, sample_pdf_path: Path, qtbot) -> None:
        from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
        from pdfprism.ui.dialogs.crop import CropDialog, CropPreview
        from pdfprism.ui.page_cache import PageCache

        adapter = PyMuPDFAdapter()
        adapter.open(sample_pdf_path)
        cache = PageCache()
        cache.set_adapter(adapter)
        try:
            dlg = CropDialog(
                page_index=0,
                page_width=612.0,
                page_height=792.0,
                page_cache=cache,
            )
            qtbot.addWidget(dlg)
            assert isinstance(dlg._preview, CropPreview)
        finally:
            adapter.close()

    def test_spinbox_change_updates_preview_margins(self, sample_pdf_path: Path, qtbot) -> None:
        from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
        from pdfprism.ui.dialogs.crop import CropDialog
        from pdfprism.ui.page_cache import PageCache

        adapter = PyMuPDFAdapter()
        adapter.open(sample_pdf_path)
        cache = PageCache()
        cache.set_adapter(adapter)
        try:
            dlg = CropDialog(
                page_index=0,
                page_width=612.0,
                page_height=792.0,
                page_cache=cache,
            )
            qtbot.addWidget(dlg)
            assert dlg._preview is not None
            # Change a spinbox -- preview should now reflect it.
            dlg._top.setValue(50.0)
            assert dlg._preview._margins == (50.0, 0.0, 0.0, 0.0)
        finally:
            adapter.close()

    def test_reset_syncs_preview_back_to_zero(self, sample_pdf_path: Path, qtbot) -> None:
        from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
        from pdfprism.ui.dialogs.crop import CropDialog
        from pdfprism.ui.page_cache import PageCache

        adapter = PyMuPDFAdapter()
        adapter.open(sample_pdf_path)
        cache = PageCache()
        cache.set_adapter(adapter)
        try:
            dlg = CropDialog(
                page_index=0,
                page_width=612.0,
                page_height=792.0,
                initial_margins=(50.0, 30.0, 20.0, 10.0),
                page_cache=cache,
            )
            qtbot.addWidget(dlg)
            assert dlg._preview is not None
            assert dlg._preview._margins == (50.0, 30.0, 20.0, 10.0)
            dlg._reset()
            assert dlg._preview._margins == (0.0, 0.0, 0.0, 0.0)
        finally:
            adapter.close()

    def test_initial_margins_primed_into_preview(self, sample_pdf_path: Path, qtbot) -> None:
        """Negative case: opening a dialog for a page with existing crop
        must show the retained region from the outset, not zero-crop."""
        from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
        from pdfprism.ui.dialogs.crop import CropDialog
        from pdfprism.ui.page_cache import PageCache

        adapter = PyMuPDFAdapter()
        adapter.open(sample_pdf_path)
        cache = PageCache()
        cache.set_adapter(adapter)
        try:
            dlg = CropDialog(
                page_index=0,
                page_width=612.0,
                page_height=792.0,
                initial_margins=(10.0, 20.0, 30.0, 40.0),
                page_cache=cache,
            )
            qtbot.addWidget(dlg)
            assert dlg._preview is not None
            assert dlg._preview._margins == (10.0, 20.0, 30.0, 40.0)
        finally:
            adapter.close()

    def test_render_failure_degrades_gracefully(self, qtbot) -> None:
        """Negative case: PageCache without adapter -> render returns None,
        preview is not created, dialog stays functional."""
        from pdfprism.ui.dialogs.crop import CropDialog
        from pdfprism.ui.page_cache import PageCache

        cache = PageCache()  # no adapter bound
        dlg = CropDialog(
            page_index=0,
            page_width=200.0,
            page_height=300.0,
            page_cache=cache,
        )
        qtbot.addWidget(dlg)
        # Dialog still constructs; preview is None; margins still queryable.
        assert dlg._preview is None
        assert dlg.margins == (0.0, 0.0, 0.0, 0.0)

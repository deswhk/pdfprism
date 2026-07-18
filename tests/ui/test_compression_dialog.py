"""Widget tests for CompressionDialog (PR 15)."""

from __future__ import annotations

from pdfprism.ui.dialogs.compression import CompressionDialog


class TestConstruction:
    def test_builds(self, qtbot) -> None:
        """Positive: dialog constructs cleanly."""
        dlg = CompressionDialog()
        qtbot.addWidget(dlg)
        assert dlg.windowTitle() == "Save Compressed As"


class TestPresetTransitions:
    def test_default_is_balanced(self, qtbot) -> None:
        """Positive: default preset is Balanced (75/150)."""
        dlg = CompressionDialog()
        qtbot.addWidget(dlg)
        assert dlg._radio_balanced.isChecked() is True
        assert dlg.jpeg_quality == 75
        assert dlg.image_dpi == 150

    def test_low_preset(self, qtbot) -> None:
        """Positive: Low preset sets quality=90, dpi=200."""
        dlg = CompressionDialog()
        qtbot.addWidget(dlg)
        dlg._radio_low.setChecked(True)
        assert dlg.jpeg_quality == 90
        assert dlg.image_dpi == 200

    def test_high_preset(self, qtbot) -> None:
        """Positive: High preset sets quality=50, dpi=100."""
        dlg = CompressionDialog()
        qtbot.addWidget(dlg)
        dlg._radio_high.setChecked(True)
        assert dlg.jpeg_quality == 50
        assert dlg.image_dpi == 100

    def test_custom_enables_spinboxes(self, qtbot) -> None:
        """Positive: Custom preset enables spinbox editing."""
        dlg = CompressionDialog()
        qtbot.addWidget(dlg)
        dlg._radio_custom.setChecked(True)
        assert dlg._quality_spin.isEnabled() is True
        assert dlg._dpi_spin.isEnabled() is True

    def test_non_custom_disables_spinboxes(self, qtbot) -> None:
        """Positive: preset presets disable spinbox editing."""
        dlg = CompressionDialog()
        qtbot.addWidget(dlg)
        dlg._radio_balanced.setChecked(True)
        assert dlg._quality_spin.isEnabled() is False
        assert dlg._dpi_spin.isEnabled() is False


class TestAccessors:
    def test_subset_fonts_default_true(self, qtbot) -> None:
        dlg = CompressionDialog()
        qtbot.addWidget(dlg)
        assert dlg.subset_fonts is True

    def test_garbage_collect_default_true(self, qtbot) -> None:
        dlg = CompressionDialog()
        qtbot.addWidget(dlg)
        assert dlg.garbage_collect is True

    def test_recompress_images_always_true(self, qtbot) -> None:
        dlg = CompressionDialog()
        qtbot.addWidget(dlg)
        assert dlg.recompress_images is True

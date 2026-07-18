"""Compression dialog (PR 15).

Small preset-driven dialog for the "Save Compressed As..." flow.
The user picks a preset (Low / Balanced / High / Custom) which
maps to concrete JPEG quality + image target DPI values. The
Custom option unlocks the fine-grained controls for callers who
know what they want.

The dialog is dumb: it does not touch the adapter, service, or
filesystem. Caller reads the accessor properties after ``exec``
returns Accepted and drives the actual save.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class CompressionDialog(QDialog):
    """Preset-driven compression settings picker."""

    # Preset name -> (jpeg_quality, image_dpi) tuples.
    _PRESETS = {
        "low": (90, 200),
        "balanced": (75, 150),
        "high": (50, 100),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save Compressed As")
        self.setModal(True)

        self._build_ui()
        # Balanced preset selected by default.
        self._radio_balanced.setChecked(True)
        self._on_preset_changed()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        root.addWidget(QLabel("Preset:"))
        self._radio_low = QRadioButton("Low compression (best quality)")
        self._radio_balanced = QRadioButton("Balanced (recommended)")
        self._radio_high = QRadioButton("High compression (smallest file)")
        self._radio_custom = QRadioButton("Custom")
        for radio in (
            self._radio_low,
            self._radio_balanced,
            self._radio_high,
            self._radio_custom,
        ):
            radio.toggled.connect(self._on_preset_changed)
            root.addWidget(radio)

        root.addWidget(QLabel("Custom settings:"))
        form = QFormLayout()

        self._quality_spin = QSpinBox()
        self._quality_spin.setRange(1, 100)
        self._quality_spin.setValue(75)
        form.addRow("JPEG image quality (1-100):", self._quality_spin)

        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(72, 300)
        self._dpi_spin.setValue(150)
        self._dpi_spin.setSuffix(" DPI")
        form.addRow("Image target DPI:", self._dpi_spin)

        self._subset_fonts_check = QCheckBox()
        self._subset_fonts_check.setChecked(True)
        form.addRow("Subset embedded fonts:", self._subset_fonts_check)

        self._garbage_check = QCheckBox()
        self._garbage_check.setChecked(True)
        form.addRow("Remove unused objects:", self._garbage_check)

        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_preset_changed(self) -> None:
        """Enable or disable custom controls based on preset choice.

        For non-Custom presets: disable controls and reset their
        values to the preset's canonical parameters. For Custom:
        enable controls and leave whatever values the user has set.
        """
        is_custom = self._radio_custom.isChecked()
        self._quality_spin.setEnabled(is_custom)
        self._dpi_spin.setEnabled(is_custom)

        if is_custom:
            return

        # Apply preset values.
        for radio, name in (
            (self._radio_low, "low"),
            (self._radio_balanced, "balanced"),
            (self._radio_high, "high"),
        ):
            if radio.isChecked():
                quality, dpi = self._PRESETS[name]
                self._quality_spin.setValue(quality)
                self._dpi_spin.setValue(dpi)
                break

    # ---- Public accessors ----

    @property
    def jpeg_quality(self) -> int:
        return self._quality_spin.value()

    @property
    def image_dpi(self) -> int:
        return self._dpi_spin.value()

    @property
    def subset_fonts(self) -> bool:
        return self._subset_fonts_check.isChecked()

    @property
    def garbage_collect(self) -> bool:
        return self._garbage_check.isChecked()

    @property
    def recompress_images(self) -> bool:
        """Image recompression toggle.

        Always True in PR 15; kept as a property so future PRs can
        expose it to the user (e.g. a text-only compression mode)
        without changing the dialog's public API.
        """
        return True

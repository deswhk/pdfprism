"""Crop-margins dialog for Edit -> Page -> Crop... (with PR 9.5 preview).

Collects four crop margins (top, right, bottom, left) in PDF points and
returns them as a tuple. Includes a Reset button that zeroes all four
fields, which the caller can use to clear an existing crop via
``crop_page(i, (0, 0, 0, 0))``.

The dialog renders a live preview of the page with the crop rectangle
overlaid: cropped-away regions are dimmed, the retained interior stays
clear. The preview updates whenever any margin spinbox changes.
Rendering uses the shared ``PageCache`` so a page opened elsewhere in
the app is not re-rasterized.

The dialog's public contract (``margins`` property, ``page_index`` in
the title, initial margins argument) is unchanged from PR 8; the
preview is purely additive.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pdfprism.ui.page_cache import PageCache

# The preview is deliberately small so the dialog stays compact on any
# reasonable screen. This is the *widget* target size; the pixmap
# inside is scaled to fit while preserving aspect ratio.
_PREVIEW_MAX_WIDTH = 280
_PREVIEW_MAX_HEIGHT = 360
# Dim colour applied to cropped-away regions. Semi-transparent black
# reads as "this is being trimmed" without hiding the underlying page.
_DIM_COLOUR = QColor(0, 0, 0, 140)
# Retained-area outline. Thin, high-contrast; sits atop the dim regions
# so the crop rectangle is unambiguous.
_OUTLINE_COLOUR = QColor(46, 134, 222)  # calm blue, distinct from dim
_OUTLINE_WIDTH = 2


class CropPreview(QWidget):
    """Widget that renders a page pixmap with a live crop overlay.

    The pixmap is set once at construction (or when ``set_pixmap`` is
    called explicitly). Margins are updated live via ``set_margins`` --
    each call triggers a repaint but not a re-render.

    Coordinate translation: margins are in PDF points; the pixmap was
    rendered at ``page_width`` PDF points wide and ``pixmap.width()``
    pixels wide. The scale factor ``pixmap.width() / page_width``
    converts point-space margins to pixel-space overlay geometry.
    """

    def __init__(
        self,
        pixmap: QPixmap,
        page_width: float,
        page_height: float,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._page_width = page_width
        self._page_height = page_height
        self._margins: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        # Scale the incoming pixmap DOWN if it exceeds the preview
        # budget; otherwise keep the source dimensions to avoid
        # upscaling artefacts on small thumbnails.
        if pixmap.width() > _PREVIEW_MAX_WIDTH or pixmap.height() > _PREVIEW_MAX_HEIGHT:
            self._pixmap = pixmap.scaled(
                _PREVIEW_MAX_WIDTH,
                _PREVIEW_MAX_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            self._pixmap = pixmap
        # Fix the widget to the (possibly scaled) pixmap size so layout is stable.
        self.setFixedSize(self._pixmap.size())

    # ---- Public API ---------------------------------------------------------

    def set_margins(self, margins: tuple[float, float, float, float]) -> None:
        """Update the overlay and repaint. Margins in PDF points."""
        self._margins = margins
        self.update()

    # ---- Painting -----------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802  # Qt override
        painter = QPainter(self)
        try:
            # 1. Draw the page pixmap.
            painter.drawPixmap(0, 0, self._pixmap)

            # 2. Compute the retained (interior) rectangle in widget pixels.
            interior = self._retained_rect()

            # 3. Dim the four cropped-away regions around the interior.
            #    Painted as four rects (top / bottom / left / right band)
            #    so the interior stays clear (no overdraw).
            self._draw_dim_bands(painter, interior)

            # 4. Outline the interior for a crisp crop-rectangle affordance.
            pen = painter.pen()
            pen.setColor(_OUTLINE_COLOUR)
            pen.setWidth(_OUTLINE_WIDTH)
            painter.setPen(pen)
            painter.drawRect(interior)
        finally:
            painter.end()

    # ---- Geometry helpers ---------------------------------------------------

    def _retained_rect(self) -> QRect:
        """Return the interior (retained) rectangle in widget pixel space."""
        top, right, bottom, left = self._margins
        # Scale factor: widget pixels per PDF point.
        sx = self._pixmap.width() / self._page_width
        sy = self._pixmap.height() / self._page_height
        x = int(round(left * sx))
        y = int(round(top * sy))
        # Clamp width/height to non-negative to avoid Qt drawing errors
        # when margins meet in the middle (over-crop). The adapter
        # rejects margins that leave a zero-area cropbox; the preview
        # just visualises the degenerate case gracefully.
        w = max(0, self._pixmap.width() - int(round((left + right) * sx)))
        h = max(0, self._pixmap.height() - int(round((top + bottom) * sy)))
        return QRect(x, y, w, h)

    def _draw_dim_bands(self, painter: QPainter, interior: QRect) -> None:
        """Fill the four bands *around* ``interior`` with the dim colour."""
        w = self._pixmap.width()
        h = self._pixmap.height()
        painter.fillRect(0, 0, w, interior.top(), _DIM_COLOUR)  # top band
        painter.fillRect(
            0,
            interior.bottom() + 1,
            w,
            h - (interior.bottom() + 1),
            _DIM_COLOUR,
        )  # bottom band
        painter.fillRect(
            0,
            interior.top(),
            interior.left(),
            interior.height(),
            _DIM_COLOUR,
        )  # left band
        painter.fillRect(
            interior.right() + 1,
            interior.top(),
            w - (interior.right() + 1),
            interior.height(),
            _DIM_COLOUR,
        )  # right band


class CropDialog(QDialog):
    """Modal: four margin fields (top/right/bottom/left) in PDF points.

    PR 9.5: a live preview widget sits above the form. The preview is
    optional -- if no ``page_cache`` is supplied (matching PR 8 callers
    that predate the preview), the dialog degrades gracefully to the
    old form-only layout.
    """

    def __init__(
        self,
        page_index: int,
        page_width: float,
        page_height: float,
        initial_margins: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        page_cache: PageCache | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Crop Page {page_index + 1}")
        self.setModal(True)
        self._page_width = page_width
        self._page_height = page_height

        info_label = QLabel(
            f"Page {page_index + 1} dimensions: "
            f"{page_width:.1f} × {page_height:.1f} points "
            f"({page_width / 72:.2f} × {page_height / 72:.2f} inches)"
        )
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # ---- Spinboxes: range 0..(dim - 1) so the crop never collapses.
        top, right, bottom, left = initial_margins
        self._top = self._make_spin(page_height - 1.0, top)
        self._right = self._make_spin(page_width - 1.0, right)
        self._bottom = self._make_spin(page_height - 1.0, bottom)
        self._left = self._make_spin(page_width - 1.0, left)

        # ---- Preview (optional; only when a cache is provided) -----------
        self._preview: CropPreview | None = None
        if page_cache is not None:
            pixmap = self._render_preview(page_cache, page_index)
            if pixmap is not None and not pixmap.isNull():
                self._preview = CropPreview(pixmap, page_width, page_height, self)
                # Prime with the initial margins so opening an existing
                # crop shows the current retained region on first paint.
                self._preview.set_margins(initial_margins)
                # Wire live updates from spinboxes.
                for spin in (self._top, self._right, self._bottom, self._left):
                    spin.valueChanged.connect(self._on_margins_changed)

        form = QFormLayout()
        form.addRow("Top (points):", self._top)
        form.addRow("Right (points):", self._right)
        form.addRow("Bottom (points):", self._bottom)
        form.addRow("Left (points):", self._left)

        reset_btn = QPushButton("Reset (clear crop)")
        reset_btn.clicked.connect(self._reset)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.addWidget(reset_btn)
        button_row.addStretch(1)
        button_row.addWidget(button_box)

        layout = QVBoxLayout(self)
        layout.addWidget(info_label)
        layout.addSpacing(6)
        if self._preview is not None:
            preview_row = QHBoxLayout()
            preview_row.addStretch(1)
            preview_row.addWidget(self._preview)
            preview_row.addStretch(1)
            layout.addLayout(preview_row)
            layout.addSpacing(6)
        layout.addLayout(form)
        layout.addSpacing(6)
        layout.addLayout(button_row)

    # ---- Preview helpers ----------------------------------------------------

    def _render_preview(self, page_cache: PageCache, page_index: int) -> QPixmap | None:
        """Render the page for preview via the shared cache.

        Uses a modest zoom so the pixmap comfortably fits the preview
        budget without pixellation after scaling. Returns ``None`` if
        the page cannot be rendered (e.g., cache has no adapter bound).
        """
        # 0.25 is a reasonable middle ground: enough detail for the
        # user to recognise the page, small enough to render quickly.
        try:
            return page_cache.get_or_render(page_index, 0.25)
        except Exception:  # noqa: BLE001
            return None

    def _on_margins_changed(self) -> None:
        """Spinbox valueChanged handler: push new margins to the preview."""
        if self._preview is not None:
            self._preview.set_margins(self.margins)

    # ---- Spinbox factory + reset -------------------------------------------

    @staticmethod
    def _make_spin(maximum: float, value: float) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(0.0, max(maximum, 0.0))
        sb.setDecimals(2)
        sb.setSingleStep(1.0)
        sb.setValue(value)
        return sb

    def _reset(self) -> None:
        for sb in (self._top, self._right, self._bottom, self._left):
            sb.setValue(0.0)
        # Explicitly repaint even if valueChanged didn't fire (all
        # spinboxes may already be at zero when Reset is clicked).
        if self._preview is not None:
            self._preview.set_margins(self.margins)

    # ---- Public API ---------------------------------------------------------

    @property
    def margins(self) -> tuple[float, float, float, float]:
        """``(top, right, bottom, left)`` in PDF points."""
        return (
            self._top.value(),
            self._right.value(),
            self._bottom.value(),
            self._left.value(),
        )

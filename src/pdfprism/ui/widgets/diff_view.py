"""Diff view widget (PR 17a).

Two-pane container showing a side-by-side comparison of two documents
with word-level highlights. Added to MainWindow as a tab.

DiffView owns:
- Two ``PyMuPDFAdapter`` instances (one per document)
- Two ``DiffPane`` widgets (left and right)
- A ``DiffResult`` with change regions and stats
- Header showing filenames + stats
- Toolbar with sync-scroll toggle and prev/next navigation
- Footer info label explaining the diff is text-only

Sync scroll: both panes share the same vertical scroll position. When
the user scrolls one pane, the other follows. When toggled off, panes
scroll independently.

The interface mirrors DocumentView for MainWindow tab compatibility:
- ``path`` -- returns the left document's path (for tab title)
- ``close_document()`` -- releases both adapters
- ``is_modified`` -- always False (read-only view)
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.services.diff import DiffResult, DiffService
from pdfprism.ui.widgets.diff_pane import DiffPane


class DiffView(QWidget):
    """Side-by-side text-diff comparison of two PDFs."""

    # DELETION on the left pane (light red), INSERTION on the right pane
    # (light green). RGBA tuples.
    DELETE_COLOR = (255, 200, 200, 128)
    INSERT_COLOR = (200, 255, 200, 128)

    def __init__(
        self,
        left_path: Path,
        right_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._left_path = left_path
        self._right_path = right_path

        # Open both docs. If either fails, propagate to caller.
        self._adapter_left = PyMuPDFAdapter()
        self._adapter_left.open(left_path)
        self._adapter_right = PyMuPDFAdapter()
        self._adapter_right.open(right_path)

        # Compute the diff
        service = DiffService()
        self._diff: DiffResult = service.diff_documents(self._adapter_left, self._adapter_right)

        # Track diff regions for prev/next navigation
        self._nav_index = -1
        self._nav_items_index = -1
        self._syncing = False

        self._build_ui()
        self._apply_highlights()
        # PR 17a: auto-scroll to first diff so user sees content immediately.
        self._on_next_diff()  # auto-scroll to first diff on open

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Header row: filenames + stats
        header_row = QHBoxLayout()
        self._left_name = QLabel(self._left_path.name)
        self._left_name.setStyleSheet("font-weight: bold;")
        header_row.addWidget(self._left_name, stretch=1)
        self._stats = QLabel(self._format_stats())
        self._stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_row.addWidget(self._stats, stretch=1)
        self._right_name = QLabel(self._right_path.name)
        self._right_name.setStyleSheet("font-weight: bold;")
        self._right_name.setAlignment(Qt.AlignmentFlag.AlignRight)
        header_row.addWidget(self._right_name, stretch=1)
        root.addLayout(header_row)

        # Toolbar row: sync-scroll toggle + prev/next
        tool_row = QHBoxLayout()
        self._sync_check = QCheckBox("Sync scroll")
        self._sync_check.setChecked(True)
        tool_row.addWidget(self._sync_check)
        tool_row.addStretch()

        self._prev_button = QPushButton("Previous diff")
        self._prev_button.clicked.connect(self._on_prev_diff)
        tool_row.addWidget(self._prev_button)
        self._next_button = QPushButton("Next diff")
        self._next_button.clicked.connect(self._on_next_diff)
        tool_row.addWidget(self._next_button)
        self._position_label = QLabel("")
        self._position_label.setStyleSheet("color: gray; font-size: 10px; padding-left: 8px;")
        tool_row.addWidget(self._position_label)
        root.addLayout(tool_row)

        # Side-by-side splitter with the two panes
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._left_pane = DiffPane(
            self._adapter_left,
            highlight_color=self.DELETE_COLOR,
        )
        self._right_pane = DiffPane(
            self._adapter_right,
            highlight_color=self.INSERT_COLOR,
        )
        self._splitter.addWidget(self._left_pane)
        self._splitter.addWidget(self._right_pane)
        self._splitter.setSizes([500, 500])
        root.addWidget(self._splitter, stretch=1)

        # Footer info
        footer = QLabel(
            "Text-only comparison. Moved sections may appear as both deletion and insertion."
        )
        footer.setStyleSheet("color: gray; font-size: 10px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(footer)

        # Wire sync scroll (both axes)
        self._left_pane.scroll_changed.connect(self._on_left_scrolled)
        self._right_pane.scroll_changed.connect(self._on_right_scrolled)
        self._left_pane.h_scroll_changed.connect(self._on_left_h_scrolled)
        self._right_pane.h_scroll_changed.connect(self._on_right_h_scrolled)

    def _format_stats(self) -> str:
        pages_a = len(self._diff.pages_touched_a)
        pages_b = len(self._diff.pages_touched_b)
        base = (
            f"{self._diff.additions_count} additions, "
            f"{self._diff.deletions_count} deletions "
            f"({pages_a} pages left, {pages_b} pages right)"
        )
        if self._diff.image_changes_count > 0:
            base += f", {self._diff.image_changes_count} image change(s)"
        return base

    def _apply_highlights(self) -> None:
        """Convert diff regions + image diffs to per-page bbox lists.

        Text: red on left / green on right.
        Images (PR 17b): magenta on the pane where the change is visible
        (both panes for ``replaced``).
        """
        left_bboxes: dict[int, list[tuple[float, float, float, float]]] = {}
        right_bboxes: dict[int, list[tuple[float, float, float, float]]] = {}
        for region in self._diff.regions:
            if region.kind in ("delete", "replace"):
                for w in region.words_a:
                    left_bboxes.setdefault(w.page_index, []).append(w.bbox)
            if region.kind in ("insert", "replace"):
                for w in region.words_b:
                    right_bboxes.setdefault(w.page_index, []).append(w.bbox)
        self._left_pane.set_highlights(left_bboxes)
        self._right_pane.set_highlights(right_bboxes)

        # PR 17b: image highlights
        left_images: dict[int, list[tuple[float, float, float, float]]] = {}
        right_images: dict[int, list[tuple[float, float, float, float]]] = {}
        for idiff in self._diff.image_diffs:
            if idiff.left is not None:
                left_images.setdefault(idiff.left.page_index, []).append(idiff.left.bbox)
            if idiff.right is not None:
                right_images.setdefault(idiff.right.page_index, []).append(idiff.right.bbox)
        self._left_pane.set_image_highlights(left_images)
        self._right_pane.set_image_highlights(right_images)

    def _on_left_scrolled(self, value: int) -> None:
        if not self._sync_check.isChecked():
            return
        if self._syncing:
            return
        self._syncing = True
        try:
            self._right_pane.sync_scroll_to(value)
        finally:
            self._syncing = False

    def _on_right_scrolled(self, value: int) -> None:
        if not self._sync_check.isChecked():
            return
        if self._syncing:
            return
        self._syncing = True
        try:
            self._left_pane.sync_scroll_to(value)
        finally:
            self._syncing = False

    def _on_left_h_scrolled(self, value: int) -> None:
        if not self._sync_check.isChecked():
            return
        if self._syncing:
            return
        self._syncing = True
        try:
            self._right_pane.sync_h_scroll_to(value)
        finally:
            self._syncing = False

    def _on_right_h_scrolled(self, value: int) -> None:
        if not self._sync_check.isChecked():
            return
        if self._syncing:
            return
        self._syncing = True
        try:
            self._left_pane.sync_h_scroll_to(value)
        finally:
            self._syncing = False

    def _get_non_equal_regions(self):
        """Return list of (index, region) for regions that are diffs."""
        return [(i, r) for i, r in enumerate(self._diff.regions) if r.kind != "equal"]

    def _get_nav_items(self):
        """PR 17b: unified nav list -- text regions + image diffs.

        Returns list of (kind, item, sort_key) where:
        - kind is "text" or "image"
        - item is a DiffRegion (text) or ImageDiff (image)
        - sort_key is (page_index, y_coord) for stable ordering
        """
        items = []
        for _i, r in enumerate(self._diff.regions):
            if r.kind == "equal":
                continue
            word = r.words_a[0] if r.words_a else (r.words_b[0] if r.words_b else None)
            if word is None:
                continue
            sort_key = (word.page_index, word.bbox[1])
            items.append(("text", r, sort_key))
        for idiff in self._diff.image_diffs:
            ref = idiff.left if idiff.left is not None else idiff.right
            if ref is None:
                continue
            sort_key = (ref.page_index, ref.bbox[1])
            items.append(("image", idiff, sort_key))
        items.sort(key=lambda x: x[2])
        return items

    def _on_prev_diff(self) -> None:
        items = self._get_nav_items()
        if not items:
            self._notify("No differences found")
            return
        target_idx = self._nav_items_index - 1
        if target_idx < 0:
            target_idx = len(items) - 1  # wrap
        self._nav_items_index = target_idx
        kind, item, _ = items[target_idx]
        self._nav_to_item(kind, item)
        self._notify_nav_position(target_idx, len(items), kind, item)

    def _on_next_diff(self) -> None:
        items = self._get_nav_items()
        if not items:
            self._notify("No differences found")
            return
        target_idx = self._nav_items_index + 1
        if target_idx >= len(items):
            target_idx = 0  # wrap
        self._nav_items_index = target_idx
        kind, item, _ = items[target_idx]
        self._nav_to_item(kind, item)
        self._notify_nav_position(target_idx, len(items), kind, item)

    def _nav_to_item(self, kind: str, item) -> None:
        """PR 17b: dispatch nav to region or image handler."""
        if kind == "text":
            self._scroll_to_region(item)
        elif kind == "image":
            self._scroll_to_image_diff(item)

    def _scroll_to_image_diff(self, idiff) -> None:
        """Scroll to an image diff, highlighting on the relevant pane(s)."""
        left_current: dict[int, list[tuple[float, float, float, float]]] = {}
        right_current: dict[int, list[tuple[float, float, float, float]]] = {}
        if idiff.left is not None:
            left_current.setdefault(idiff.left.page_index, []).append(idiff.left.bbox)
        if idiff.right is not None:
            right_current.setdefault(idiff.right.page_index, []).append(idiff.right.bbox)
        self._left_pane.set_current_highlights(left_current)
        self._right_pane.set_current_highlights(right_current)

        target = idiff.left if idiff.left is not None else idiff.right
        pane = self._left_pane if idiff.left is not None else self._right_pane
        if target is None:
            return
        y = 0
        for pi, pix in enumerate(pane._base_pixmaps):
            if pi >= target.page_index:
                break
            y += pix.height() + pane._layout.spacing()
        y += int(target.bbox[1])
        pane.verticalScrollBar().setValue(max(0, y - 40))

    def _notify_nav_position(self, current: int, total: int, kind: str, item) -> None:
        """PR 17b: unified nav notification for text + image diffs."""
        if kind == "text":
            label = {
                "replace": "replace",
                "insert": "insertion",
                "delete": "deletion",
            }.get(item.kind, item.kind)
        elif kind == "image":
            label = f"image {item.kind}"
        else:
            label = kind
        self._notify(f"Diff {current + 1} of {total} ({label})")

    def _scroll_to_region(self, region) -> None:
        """Scroll both panes AND set current-diff highlights on both."""
        # Update current highlights on BOTH panes before scrolling
        left_current: dict[int, list[tuple[float, float, float, float]]] = {}
        for w in region.words_a:
            left_current.setdefault(w.page_index, []).append(w.bbox)
        right_current: dict[int, list[tuple[float, float, float, float]]] = {}
        for w in region.words_b:
            right_current.setdefault(w.page_index, []).append(w.bbox)
        self._left_pane.set_current_highlights(left_current)
        self._right_pane.set_current_highlights(right_current)

        # Now scroll to the first word of the region on whichever pane has one.
        target = None
        pane = None
        if region.words_a:
            target = region.words_a[0]
            pane = self._left_pane
        elif region.words_b:
            target = region.words_b[0]
            pane = self._right_pane
        else:
            return
        y = 0
        for pi, pix in enumerate(pane._base_pixmaps):
            if pi >= target.page_index:
                break
            y += pix.height() + pane._layout.spacing()
        y += int(target.bbox[1])
        pane.verticalScrollBar().setValue(max(0, y - 40))

    def _notify(self, message: str) -> None:
        """Update the position status label with a message."""
        self._position_label.setText(message)

    def _notify_position(self, current: int, total: int, region) -> None:
        """Report which diff we jumped to and its kind."""
        kind_label = {
            "replace": "replace",
            "insert": "insertion",
            "delete": "deletion",
        }.get(region.kind, region.kind)
        self._notify(f"Diff {current + 1} of {total} ({kind_label})")

        # ---- Public API expected by MainWindow tab machinery ----

    @property
    def path(self) -> Path:
        """Left document path -- used for tab title/tooltip."""
        return self._left_path

    @property
    def is_modified(self) -> bool:
        """DiffView is read-only. Always False."""
        return False

    def close_document(self) -> None:
        """Release both adapters. Called by MainWindow on tab close."""
        try:
            self._adapter_left.close()
        except Exception:
            pass
        try:
            self._adapter_right.close()
        except Exception:
            pass

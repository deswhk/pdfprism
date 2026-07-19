"""Widget tests for DiffPane + DiffView (PR 17a)."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from pdfprism.ui.widgets.diff_pane import DiffPane
from pdfprism.ui.widgets.diff_view import DiffView


def _make_doc(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    d = pymupdf.open()
    p = d.new_page(width=612, height=792)
    p.insert_text((72, 100), text, fontsize=12)
    d.save(str(path))
    d.close()
    return path


class TestMergeLineBboxes:
    def test_merges_same_line_bboxes(self) -> None:
        """Positive: adjacent same-line bboxes merged into one rectangle."""
        # Three word boxes on the same y-line
        bboxes = [
            (72.0, 100.0, 100.0, 115.0),
            (105.0, 100.0, 140.0, 115.0),
            (145.0, 100.0, 180.0, 115.0),
        ]
        merged = DiffPane._merge_line_bboxes(bboxes)
        assert len(merged) == 1
        assert merged[0][0] == 72.0
        assert merged[0][2] == 180.0

    def test_splits_across_lines(self) -> None:
        """Positive: bboxes on different y-lines produce separate rects."""
        bboxes = [
            (72.0, 100.0, 100.0, 115.0),
            (72.0, 130.0, 100.0, 145.0),
        ]
        merged = DiffPane._merge_line_bboxes(bboxes)
        assert len(merged) == 2


class TestDiffView:
    def test_constructs_and_reports_diffs(self, qtbot, tmp_path: Path) -> None:
        """Positive: DiffView constructs on two docs; diff counts populate."""
        p_a = _make_doc(tmp_path, "a.pdf", "The quick brown fox")
        p_b = _make_doc(tmp_path, "b.pdf", "The quick red fox")
        view = DiffView(p_a, p_b)
        qtbot.addWidget(view)
        assert view.path == p_a
        assert view.is_modified is False
        assert view._diff.additions_count == 1
        assert view._diff.deletions_count == 1
        view.close_document()


class TestDiffViewWithImages:
    def _solid_png(self, r: int, g: int, b: int, size: int = 8) -> bytes:
        import pymupdf

        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.Rect(0, 0, size, size), False)
        pix.set_rect(pix.irect, (r, g, b))
        return pix.tobytes("png")

    def _make_doc_with_image(self, tmp_path: Path, name: str, img_bytes: bytes) -> Path:
        import pymupdf

        path = tmp_path / name
        d = pymupdf.open()
        p = d.new_page(width=612, height=792)
        p.insert_image(pymupdf.Rect(72, 100, 200, 200), stream=img_bytes)
        d.save(str(path))
        d.close()
        return path

    def test_reports_image_changes(self, qtbot, tmp_path: Path) -> None:
        red = self._solid_png(255, 0, 0)
        blue = self._solid_png(0, 0, 255)
        p_a = self._make_doc_with_image(tmp_path, "a.pdf", red)
        p_b = self._make_doc_with_image(tmp_path, "b.pdf", blue)
        view = DiffView(p_a, p_b)
        qtbot.addWidget(view)
        assert view._diff.image_changes_count == 1
        assert view._diff.image_diffs[0].kind == "replaced"
        view.close_document()

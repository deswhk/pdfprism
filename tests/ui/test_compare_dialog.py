"""Widget tests for CompareDialog (PR 17a)."""

from __future__ import annotations

from pathlib import Path

from pdfprism.ui.dialogs.compare import CompareDialog


class TestCompareDialog:
    def test_empty_tabs_compare_disabled(self, qtbot) -> None:
        """Positive: no open tabs -> Compare disabled (no defaulted paths)."""
        dlg = CompareDialog(open_tab_paths=[])
        qtbot.addWidget(dlg)
        assert dlg._compare_button.isEnabled() is False

    def test_same_doc_disabled(self, qtbot) -> None:
        """Positive: same doc on both sides -> Compare disabled."""
        p = Path("/fake/only.pdf")
        dlg = CompareDialog(open_tab_paths=[p])
        qtbot.addWidget(dlg)
        # Both sides default to the same first tab -> disabled
        assert dlg._compare_button.isEnabled() is False

    def test_two_different_docs_enabled(self, qtbot) -> None:
        """Positive: distinct paths on both sides -> Compare enabled."""
        dlg = CompareDialog(
            open_tab_paths=[Path("/fake/one.pdf"), Path("/fake/two.pdf")],
        )
        qtbot.addWidget(dlg)
        # Left defaults to index 0 (one.pdf), set right to index 1 (two.pdf)
        dlg._right_combo.setCurrentIndex(1)
        assert dlg._compare_button.isEnabled() is True

    def test_path_accessors(self, qtbot) -> None:
        """Positive: left_path/right_path return selected paths."""
        p1 = Path("/fake/one.pdf")
        p2 = Path("/fake/two.pdf")
        dlg = CompareDialog(open_tab_paths=[p1, p2])
        qtbot.addWidget(dlg)
        dlg._left_combo.setCurrentIndex(0)
        dlg._right_combo.setCurrentIndex(1)
        assert dlg.left_path == p1
        assert dlg.right_path == p2

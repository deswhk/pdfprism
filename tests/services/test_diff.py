"""Unit tests for DiffService (PR 17a)."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.services.diff import DiffService


def _make_doc(tmp_path: Path, name: str, text: str) -> Path:
    """Create a single-page doc with the given text."""
    path = tmp_path / name
    d = pymupdf.open()
    p = d.new_page(width=612, height=792)
    p.insert_text((72, 100), text, fontsize=12)
    d.save(str(path))
    d.close()
    return path


class TestDiffDocuments:
    def test_identical_docs(self, tmp_path: Path) -> None:
        """Positive: identical docs -> single equal region, no changes."""
        p_a = _make_doc(tmp_path, "a.pdf", "The quick brown fox")
        p_b = _make_doc(tmp_path, "b.pdf", "The quick brown fox")
        adapter_a = PyMuPDFAdapter()
        adapter_a.open(p_a)
        adapter_b = PyMuPDFAdapter()
        adapter_b.open(p_b)
        try:
            result = DiffService().diff_documents(adapter_a, adapter_b)
        finally:
            adapter_a.close()
            adapter_b.close()
        assert result.additions_count == 0
        assert result.deletions_count == 0
        assert len(result.regions) == 1
        assert result.regions[0].kind == "equal"

    def test_word_substitution(self, tmp_path: Path) -> None:
        """Positive: single-word replacement -> replace region."""
        p_a = _make_doc(tmp_path, "a.pdf", "The quick brown fox")
        p_b = _make_doc(tmp_path, "b.pdf", "The quick red fox")
        adapter_a = PyMuPDFAdapter()
        adapter_a.open(p_a)
        adapter_b = PyMuPDFAdapter()
        adapter_b.open(p_b)
        try:
            result = DiffService().diff_documents(adapter_a, adapter_b)
        finally:
            adapter_a.close()
            adapter_b.close()
        assert result.additions_count == 1
        assert result.deletions_count == 1
        replace_regions = [r for r in result.regions if r.kind == "replace"]
        assert len(replace_regions) == 1
        assert [w.word for w in replace_regions[0].words_a] == ["brown"]
        assert [w.word for w in replace_regions[0].words_b] == ["red"]

    def test_word_insertion(self, tmp_path: Path) -> None:
        """Positive: pure insertion -> insert region on B side only."""
        p_a = _make_doc(tmp_path, "a.pdf", "The fox")
        p_b = _make_doc(tmp_path, "b.pdf", "The quick fox")
        adapter_a = PyMuPDFAdapter()
        adapter_a.open(p_a)
        adapter_b = PyMuPDFAdapter()
        adapter_b.open(p_b)
        try:
            result = DiffService().diff_documents(adapter_a, adapter_b)
        finally:
            adapter_a.close()
            adapter_b.close()
        assert result.additions_count == 1
        assert result.deletions_count == 0
        insert_regions = [r for r in result.regions if r.kind == "insert"]
        assert len(insert_regions) == 1
        assert [w.word for w in insert_regions[0].words_b] == ["quick"]

    def test_word_deletion(self, tmp_path: Path) -> None:
        """Positive: pure deletion -> delete region on A side only."""
        p_a = _make_doc(tmp_path, "a.pdf", "The quick fox")
        p_b = _make_doc(tmp_path, "b.pdf", "The fox")
        adapter_a = PyMuPDFAdapter()
        adapter_a.open(p_a)
        adapter_b = PyMuPDFAdapter()
        adapter_b.open(p_b)
        try:
            result = DiffService().diff_documents(adapter_a, adapter_b)
        finally:
            adapter_a.close()
            adapter_b.close()
        assert result.additions_count == 0
        assert result.deletions_count == 1
        delete_regions = [r for r in result.regions if r.kind == "delete"]
        assert len(delete_regions) == 1
        assert [w.word for w in delete_regions[0].words_a] == ["quick"]

    def test_case_insensitive_matching(self, tmp_path: Path) -> None:
        """Positive: case-differing docs with case_sensitive=False -> no diffs."""
        p_a = _make_doc(tmp_path, "a.pdf", "The Quick Brown Fox")
        p_b = _make_doc(tmp_path, "b.pdf", "the quick brown fox")
        adapter_a = PyMuPDFAdapter()
        adapter_a.open(p_a)
        adapter_b = PyMuPDFAdapter()
        adapter_b.open(p_b)
        try:
            result = DiffService().diff_documents(adapter_a, adapter_b, case_sensitive=False)
        finally:
            adapter_a.close()
            adapter_b.close()
        assert result.additions_count == 0
        assert result.deletions_count == 0

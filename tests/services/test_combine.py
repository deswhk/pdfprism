"""Unit tests for CombineService (PR 16)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.services.combine import CombineService


class TestCombineDelegate:
    def test_delegates_with_kwargs(self, tmp_path: Path) -> None:
        """Positive: service.combine forwards args to adapter."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        adapter.combine_documents.return_value = 7
        service = CombineService(adapter)

        result = service.combine(
            [tmp_path / "a.pdf", tmp_path / "b.pdf"],
            tmp_path / "out.pdf",
        )
        assert result == 7
        adapter.combine_documents.assert_called_once()
        args, kwargs = adapter.combine_documents.call_args
        assert args[0] == [tmp_path / "a.pdf", tmp_path / "b.pdf"]
        assert args[1] == tmp_path / "out.pdf"

    def test_returns_page_count(self, tmp_path: Path) -> None:
        """Positive: returns whatever adapter returns."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        adapter.combine_documents.return_value = 42
        service = CombineService(adapter)
        result = service.combine([tmp_path / "x.pdf"], tmp_path / "out.pdf")
        assert result == 42

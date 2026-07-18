"""Unit tests for CompressionService (PR 15)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.services.compression import CompressionService


class TestSaveCompressedDelegate:
    def test_delegates_with_kwargs(self, tmp_path: Path) -> None:
        """Positive: service.save_compressed forwards all kwargs to adapter."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        adapter.save_compressed.return_value = (10_000, 3_000)
        service = CompressionService(adapter)
        result = service.save_compressed(
            tmp_path / "out.pdf",
            jpeg_quality=60,
            image_dpi=100,
            recompress_images=True,
            subset_fonts=False,
            garbage_collect=True,
        )
        assert result == (10_000, 3_000)
        adapter.save_compressed.assert_called_once()
        _, kwargs = adapter.save_compressed.call_args
        assert kwargs["jpeg_quality"] == 60
        assert kwargs["image_dpi"] == 100
        assert kwargs["recompress_images"] is True
        assert kwargs["subset_fonts"] is False
        assert kwargs["garbage_collect"] is True

    def test_returns_size_tuple(self, tmp_path: Path) -> None:
        """Positive: returns whatever adapter returns."""
        adapter = MagicMock(spec=PyMuPDFAdapter)
        adapter.save_compressed.return_value = (5_000, 2_000)
        service = CompressionService(adapter)
        result = service.save_compressed(tmp_path / "out.pdf")
        assert result == (5_000, 2_000)

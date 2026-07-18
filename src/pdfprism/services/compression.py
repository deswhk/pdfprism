"""Compression service (PR 15).

Thin wrapper around ``PyMuPDFAdapter.save_compressed`` that gives
callers a consistent service-layer entry point matching the shape
of ``RedactionService`` and other services in the app.

The service is stateless: it holds no per-document state. Each call
takes an adapter (which owns the doc) and the compression parameters,
delegates to the adapter, and returns the size tuple.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter

logger = logging.getLogger(__name__)


class CompressionService:
    """Save a compressed copy of a document via a PyMuPDF adapter."""

    def __init__(self, adapter: PyMuPDFAdapter) -> None:
        self._adapter = adapter

    def save_compressed(
        self,
        output_path: Path,
        *,
        jpeg_quality: int = 75,
        image_dpi: int = 150,
        recompress_images: bool = True,
        subset_fonts: bool = True,
        garbage_collect: bool = True,
        progress_callback=None,
    ) -> tuple[int, int]:
        """Save a compressed copy of the document.

        Delegates to ``PyMuPDFAdapter.save_compressed``. See that
        method for parameter semantics.

        Returns:
            (original_size_bytes, compressed_size_bytes)
        """
        original, compressed = self._adapter.save_compressed(
            output_path,
            jpeg_quality=jpeg_quality,
            image_dpi=image_dpi,
            recompress_images=recompress_images,
            subset_fonts=subset_fonts,
            garbage_collect=garbage_collect,
            progress_callback=progress_callback,
        )
        reduction_pct = 100.0 * (1 - compressed / original) if original else 0.0
        logger.info(
            "Compressed %d bytes -> %d bytes (%.1f%% reduction) -> %s",
            original,
            compressed,
            reduction_pct,
            output_path.name,
        )
        return (original, compressed)

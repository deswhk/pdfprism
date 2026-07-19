"""Combine service (PR 16).

Thin wrapper around ``PyMuPDFAdapter.combine_documents`` that gives
callers a consistent service-layer entry point matching the shape
of other services in the app.

Stateless: no per-document state. Each call takes an adapter (used
only for its combine_documents entry point) and the compression
parameters, delegates to the adapter, and returns the combined page
count.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter

logger = logging.getLogger(__name__)


class CombineService:
    """Combine multiple PDFs into a single output document."""

    def __init__(self, adapter: PyMuPDFAdapter) -> None:
        self._adapter = adapter

    def combine(
        self,
        sources: list[Path],
        output_path: Path,
        *,
        progress_callback=None,
    ) -> int:
        """Combine sources into a new PDF at output_path.

        Delegates to ``PyMuPDFAdapter.combine_documents``. See that
        method for parameter semantics, encryption behavior, and
        reconciliation rules.

        Returns:
            page count of the combined document.
        """
        page_count = self._adapter.combine_documents(
            sources,
            output_path,
            progress_callback=progress_callback,
        )
        logger.info(
            "Combined %d source(s) into %s (%d pages)",
            len(sources),
            output_path.name,
            page_count,
        )
        return page_count

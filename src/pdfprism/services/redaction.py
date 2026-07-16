"""Redaction service for pdfprism (PR 12).

Thin service layer over the adapter's redaction methods. Four intents:

- ``add_redaction(page_index, rect, ...)``: mark a rectangular region
  for redaction. Non-destructive; the mark can still be reviewed or
  removed before ``apply()`` is called.

- ``list_redactions()``: return all pending redactions in page-major
  order for the review UI.

- ``remove_redaction(page_index, redaction_index)``: delete a specific
  pending mark.

- ``apply()``: destructively commit all pending redactions. Returns
  the count applied. After this call, no pending redactions remain.

Callers should still call ``adapter.save()`` (or route through
DocumentView) to persist the change. See ARCHITECTURE.md for the
save-semantics discussion (pending marks persist as annotations on
save; apply then save is the destructive path).
"""

from __future__ import annotations

import logging

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter
from pdfprism.core.types import Redaction

logger = logging.getLogger(__name__)


class RedactionService:
    """Redaction management intents.

    Wraps a bound ``PyMuPDFAdapter`` and provides four intent methods
    that map user intent (from PageView drag or menu action) to
    adapter mutations.
    """

    def __init__(self, adapter: PyMuPDFAdapter) -> None:
        self._adapter = adapter

    def add_redaction(
        self,
        page_index: int,
        rect: tuple[float, float, float, float],
        *,
        replacement_text: str | None = None,
        fill_color: tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        """Add a pending redaction mark.

        Args:
            page_index: The 0-based page index to redact on.
            rect: (x0, y0, x1, y1) rectangle in PDF-space points.
            replacement_text: Optional overlay text drawn in the redacted
                area after apply.
            fill_color: RGB 0-255 tuple; default black.
        """
        redaction = Redaction(
            page_index=page_index,
            rect=rect,
            replacement_text=replacement_text,
            fill_color=fill_color,
        )
        self._adapter.add_redaction(redaction)
        logger.info("Redaction added on page %d: rect=%s", page_index, rect)

    def redact_words(self, page_index: int, words: list) -> int:
        """PR 12.1: batch redact each Word in the selection.

        Delegates to adapter's add_redactions_for_words. See there for
        semantics (per-word rects, session-default fill).

        Args:
            page_index: Page these words belong to.
            words: Word objects to redact. Empty list is a no-op.

        Returns:
            Count of redactions added.
        """
        count = self._adapter.add_redactions_for_words(page_index, words)
        if count:
            logger.info("Redacted %d word(s) on page %d", count, page_index)
        return count

    def list_redactions(self) -> list[Redaction]:
        """Return all pending redactions in page-major order."""
        return self._adapter.list_redactions()

    def remove_redaction(self, page_index: int, redaction_index: int) -> None:
        """Remove a specific pending redaction mark."""
        self._adapter.remove_redaction(page_index, redaction_index)
        logger.info(
            "Redaction removed from page %d (index %d)",
            page_index,
            redaction_index,
        )

    def apply(self) -> int:
        """Destructively apply all pending redactions.

        Returns:
            Count of redactions applied. Zero if nothing was pending.
        """
        count = self._adapter.apply_redactions()
        logger.info("Redactions applied: %d", count)
        return count

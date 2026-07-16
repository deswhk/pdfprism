"""Metadata service for pdfprism (PR 11).

Thin service layer over the adapter's metadata methods. Two intents:

- ``sanitize_metadata()``: one-click "clear everything sensitive from
  this document's metadata" for the user who wants to share safely.
  Clears the six standard Info dict fields, optionally also deletes
  the XMP metadata stream (PDF 2.0 metadata channel that can carry
  redundant author/creator info).

- ``set_metadata()``: passthrough for the dialog's edit-and-save
  flow. Converts empty strings (user backspaced field to empty) to
  ``None`` so the field is actually cleared, not set to ``""``.

The service does no I/O beyond the adapter mutation. Callers must
still call ``adapter.save()`` (or route through DocumentView which
handles the panel-rebind dance) to persist the changes.
"""

from __future__ import annotations

import logging

from pdfprism.core.adapters.pymupdf_adapter import PyMuPDFAdapter

logger = logging.getLogger(__name__)


class PropertiesService:
    """Metadata management intents.

    Wraps a bound ``PyMuPDFAdapter`` and provides two named intent
    methods that map user intent (from the PropertiesDialog) to
    adapter mutations. Analogous shape to ``SecurityService``.
    """

    def __init__(self, adapter: PyMuPDFAdapter) -> None:
        self._adapter = adapter

    def sanitize_metadata(self, *, delete_xmp: bool = True) -> None:
        """Clear all metadata from the document.

        Args:
            delete_xmp: If True (default), also remove the XMP metadata
                stream. Some sensitive info (author, creator, application
                producer) survives Info-dict clearing if XMP is kept.

        The Info-dict clear runs first and is unconditional; XMP
        deletion runs second and is idempotent (no-op if no XMP).
        Marks the document dirty. Caller must save() to persist.
        """
        current = self._adapter.get_metadata()
        # Set every known field to None (adapter maps to empty string
        # in the PyMuPDF Info dict).
        cleared: dict[str, str | None] = {key: None for key in current}
        self._adapter.set_metadata(cleared)
        logger.info("Metadata sanitized (info fields cleared)")

        if delete_xmp:
            self._adapter.delete_xml_metadata()
            logger.info("XMP metadata stream removed")

    def set_metadata(self, updates: dict[str, str | None]) -> None:
        """Update metadata fields.

        Empty strings are normalised to ``None`` (interpreted as "clear
        this field") so a user who backspaces a field to empty in the
        dialog gets the intuitive result.

        Args:
            updates: Field-name -> new value dict. Only keys the
                adapter recognises are applied; unknown keys are
                silently ignored (delegated to the adapter).
        """
        normalised: dict[str, str | None] = {
            key: (value if value else None) for key, value in updates.items()
        }
        self._adapter.set_metadata(normalised)
        logger.info("Metadata updated: %d field(s)", len(updates))
